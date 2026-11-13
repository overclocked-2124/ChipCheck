"""Campaign and planner logic. No simulator fault details are available here."""
import json, random, sqlite3, uuid
from pathlib import Path
import optuna
from interaction_demo import simulator

optuna.logging.set_verbosity(optuna.logging.WARNING)
KEYS = tuple(f'led{i}_value' for i in range(1, 4))

def validate(p):
    if set(p) != set(KEYS) or any(type(p[k]) is not int or not 0 <= p[k] <= 255 for k in KEYS):
        raise ValueError('Each of the three LED values must be an integer from 0 to 255')
    return p

class Campaign:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS campaigns (id TEXT PRIMARY KEY, planner TEXT, budget INTEGER, seed INTEGER)')
        self.db.execute('CREATE TABLE IF NOT EXISTS experiments (campaign TEXT, batch INTEGER, id INTEGER, requested TEXT, result TEXT, purpose TEXT, PRIMARY KEY(campaign,id))')
        self.db.commit()

    def create(self, planner, budget, seed):
        if planner not in ('random', 'tpe', 'forest') or type(budget) is not int or not 1 <= budget <= 1000 or type(seed) is not int:
            raise ValueError('Choose random, TPE or forest, a budget of 1–1000, and an integer seed')
        cid = 'CC-' + uuid.uuid4().hex[:8].upper()
        self.db.execute('INSERT INTO campaigns VALUES (?,?,?,?)', (cid, planner, budget, seed)); self.db.commit()
        return cid

    def state(self, cid):
        c = self.db.execute('SELECT planner,budget,seed FROM campaigns WHERE id=?', (cid,)).fetchone()
        if not c: raise ValueError('Campaign not found')
        rows = self.db.execute('SELECT batch,id,requested,result,purpose FROM experiments WHERE campaign=? ORDER BY id', (cid,)).fetchall()
        ex = [{'batch_id': b, 'experiment_id': i, 'parameters': json.loads(p), 'result': json.loads(r) if r else None, 'purpose': purpose} for b,i,p,r,purpose in rows]
        return {'id': cid, 'planner': c[0], 'budget': c[1], 'seed': c[2], 'experiments': ex}

    def propose(self, cid, count, purpose='explore'):
        s = self.state(cid); rows = s['experiments']
        if any(x['result'] is None for x in rows): raise ValueError('Execute the pending batch before proposing another')
        if type(count) is not int or not 1 <= count <= 100: raise ValueError('Batch size must be 1–100')
        if purpose not in ('explore', 'confirm', 'boundary'): raise ValueError('Unknown proposal purpose')
        count = min(count, s['budget'] - len(rows))
        if count <= 0: raise ValueError('Campaign budget exhausted')
        batch = max((r['batch_id'] for r in rows), default=0) + 1
        rng = random.Random(s['seed'] + batch * 982451653)
        seen = {tuple(r['parameters'][k] for k in KEYS) for r in rows}
        valid = [r for r in rows if r['result'] and r['result']['outcome'] in ('PASS','FAIL') and r['result']['measurement_quality'] == 'VALID']
        failures = [r for r in valid if r['result']['outcome'] == 'FAIL']
        if purpose == 'confirm' and not failures: raise ValueError('No failure available to confirm')
        sampler = optuna.samplers.TPESampler(seed=s['seed'] + batch, multivariate=True, warn_independent_sampling=False)
        study = optuna.create_study(direction='minimize', sampler=sampler)
        dists = {k: optuna.distributions.IntDistribution(0,255) for k in KEYS}
        for r in valid:
            study.add_trial(optuna.trial.create_trial(params=r['parameters'], distributions=dists, value=0 if r['result']['outcome']=='FAIL' else 1))
        forest = None
        if s['planner'] == 'forest' and len({r['result']['outcome'] for r in valid}) == 2:
            from sklearn.ensemble import RandomForestClassifier
            forest = RandomForestClassifier(n_estimators=80, min_samples_leaf=2, random_state=s['seed'], n_jobs=1)
            forest.fit([[r['parameters'][k] for k in KEYS] for r in valid], [r['result']['outcome'] == 'FAIL' for r in valid])
        for n in range(count):
            for _ in range(10000):
                if purpose == 'confirm': p = dict(failures[n % len(failures)]['parameters'])
                elif purpose == 'boundary' and failures:
                    base = failures[n % len(failures)]['parameters']; p = dict(base)
                    axis = n % 3; p[KEYS[axis]] = max(0,min(255,p[KEYS[axis]] + rng.choice([-1,1])*rng.choice([5,10,20,35,50])))
                elif forest is not None and n % 4 != 0:
                    pool = [[rng.randrange(256) for _ in KEYS] for _ in range(256)]
                    probs = forest.predict_proba(pool)[:, 1]
                    def score(item):
                        point, probability = item
                        distance = min((sum((point[i]-old[i])**2 for i in range(3))**0.5 for old in seen), default=442) / 442
                        return (1 - 2 * abs(float(probability) - 0.5)) + 0.3 * distance
                    point = max(zip(pool, probs), key=score)[0]
                    p = dict(zip(KEYS, point))
                elif s['planner'] == 'tpe' and n % 4 != 0:
                    trial = study.ask(); p = {k: trial.suggest_int(k,0,255) for k in KEYS}
                else: p = {k:rng.randrange(256) for k in KEYS}
                key = tuple(p[k] for k in KEYS)
                if purpose == 'confirm' or key not in seen: break
            else: raise ValueError('Could not find an unseen candidate')
            validate(p); seen.add(key)
            self.db.execute('INSERT INTO experiments VALUES (?,?,?,?,?,?)', (cid,batch,len(rows)+n+1,json.dumps(p),None,purpose))
        self.db.commit(); return self.state(cid)

    def run_pending(self, cid, executor=simulator.execute):
        s = self.state(cid)
        pending = [r for r in s['experiments'] if r['result'] is None]
        if not pending: raise ValueError('No pending batch')
        for r in pending:
            command = {'campaign_id': cid, 'batch_id': r['batch_id'], 'experiment_id': r['experiment_id'], 'command': 'RUN_INTERACTION_TEST', 'parameters': validate(r['parameters'])}
            result = executor(command)
            if any(result.get(k) != command[k] for k in ('campaign_id','batch_id','experiment_id')): raise ValueError('Result identifier mismatch')
            if result.get('outcome') not in ('PASS','FAIL','INVALID','ABORTED') or result.get('measurement_quality') not in ('VALID','INVALID'): raise ValueError('Invalid result outcome or measurement quality')
            validate(result['applied_parameters'])
            if result['outcome'] in ('PASS','FAIL') and result['measurement_quality'] != 'VALID': raise ValueError('PASS/FAIL requires valid measurement')
            self.db.execute('UPDATE experiments SET result=? WHERE campaign=? AND id=?', (json.dumps(result),cid,r['experiment_id'])); self.db.commit()
        return self.state(cid)
