"""Synthetic device; fault regions are deliberately hidden from the planner."""

def execute(command):
    p = command['parameters']
    a, b, c = (p[f'led{i}_value'] for i in range(1, 4))
    # Artificial fault regions for demonstrating discovery, not real hardware behavior.
    failed = (70 <= a <= 155 and 110 <= b <= 205 and 55 <= c <= 155) or (175 <= a <= 245 and 25 <= b <= 120 and 145 <= c <= 235)
    return {**{k: command[k] for k in ('campaign_id', 'batch_id', 'experiment_id')},
            'status': 'COMPLETED', 'applied_parameters': dict(p),
            'measurements': {'buzzer_detected': not failed, 'sound_level': 0 if failed else 62.5,
                             'frequency_hz': 0 if failed else 2000},
            'outcome': 'FAIL' if failed else 'PASS', 'measurement_quality': 'VALID', 'source': 'simulated'}
