"""Synthetic device for the laptop-only demo. The fault comes from fault_injection.py and is hidden from the planner."""
from interaction_demo.fault_injection import buzzer_should_sound


def execute(command):
    p = command['parameters']
    a, b, c = (p[f'led{i}_value'] for i in range(1, 4))
    ok = buzzer_should_sound(a, b, c)
    return {**{k: command[k] for k in ('campaign_id', 'batch_id', 'experiment_id')},
            'status': 'COMPLETED', 'applied_parameters': dict(p),
            'measurements': {'buzzer_detected': ok, 'sound_level': 62.5 if ok else 0, 'frequency_hz': 2000 if ok else 0},
            'outcome': 'PASS' if ok else 'FAIL', 'measurement_quality': 'VALID', 'source': 'simulated'}
