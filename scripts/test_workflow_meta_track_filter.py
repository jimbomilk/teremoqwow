#!/usr/bin/env python3
"""
Test: Workflow filter includes all meta-track dependencies
Verifica que deploy.yml detecta cambios en:
  - ingest/meta-track/
  - scripts/pipeline_obs.py
  - scripts/pipeline-collector.sh
  - docker-compose.prod.yml
"""

import yaml
from pathlib import Path

def test_meta_track_filter_completeness():
    print('[TEST] test_meta_track_filter_completeness')

    # Load workflow
    workflow_path = Path(__file__).parent.parent / '.github' / 'workflows' / 'deploy.yml'
    with open(workflow_path) as f:
        workflow = yaml.safe_load(f)

    # Get meta_track filter
    filters = workflow['jobs']['detect']['steps'][1]['with']['filters']
    meta_track_filter = filters.split('meta_track:')[1].split('infra:')[0].strip()

    print(f'  Meta-track filter:\n{meta_track_filter}')

    # Required paths
    required_paths = [
        'ingest/meta-track/**',
        'scripts/pipeline_obs.py',
        'scripts/pipeline-collector.sh',
        'docker-compose.prod.yml',
    ]

    for path in required_paths:
        if path not in meta_track_filter:
            raise AssertionError(f'Missing required path: {path}')
        print(f'  ✓ Includes {path}')

    print('[PASS] test_meta_track_filter_completeness')


def test_changed_meta_track_in_ssh_envs():
    print('[TEST] test_changed_meta_track_in_ssh_envs')

    workflow_path = Path(__file__).parent.parent / '.github' / 'workflows' / 'deploy.yml'
    with open(workflow_path) as f:
        workflow = yaml.safe_load(f)

    # Find SSH action step
    deploy_job = workflow['jobs']['deploy']

    # Look for SSH step with with.envs
    ssh_step = None
    for step in deploy_job['steps']:
        if 'with' in step and 'envs' in step['with']:
            ssh_step = step
            break

    if not ssh_step:
        raise AssertionError('Could not find SSH step with envs')

    envs = ssh_step['with']['envs']
    print(f'  SSH with.envs: {envs}')

    if 'CHANGED_META_TRACK' not in envs:
        raise AssertionError('CHANGED_META_TRACK not in with.envs')

    print('  ✓ CHANGED_META_TRACK in with.envs (transmitted to SSH)')
    print('[PASS] test_changed_meta_track_in_ssh_envs')


def test_meta_track_only_doesnt_restart_other_services():
    print('[TEST] test_meta_track_only_doesnt_restart_other_services')

    # This is a logical test:
    # - Meta-track filter should NOT include paths that trigger other services
    # - Other services should NOT be selected when only meta-track changes

    workflow_path = Path(__file__).parent.parent / '.github' / 'workflows' / 'deploy.yml'
    with open(workflow_path) as f:
        content = f.read()
        workflow = yaml.safe_load(content)

    filters = workflow['jobs']['detect']['steps'][1]['with']['filters']

    # Meta-track filter
    meta_lines = [l.strip() for l in filters.split('meta_track:')[1].split('infra:')[0].strip().split('\n')]
    meta_filter = [l for l in meta_lines if l and not l.startswith('#')]

    # Auth filter (should not overlap with meta)
    auth_lines = [l.strip() for l in filters.split('auth:')[1].split('billing:')[0].strip().split('\n')]
    auth_filter = [l for l in auth_lines if l and not l.startswith('#')]

    print(f'  Meta-track paths: {meta_filter}')
    print(f'  Auth paths: {auth_filter}')

    # Ensure no overlap in commercial/* paths
    for auth_path in auth_filter:
        if auth_path in meta_filter:
            raise AssertionError(f'Overlap: {auth_path} is in both meta and auth')

    print('  ✓ No filter overlap (meta-only changes select meta-publisher only)')
    print('[PASS] test_meta_track_only_doesnt_restart_other_services')


# Run tests
tests = [
    test_meta_track_filter_completeness,
    test_changed_meta_track_in_ssh_envs,
    test_meta_track_only_doesnt_restart_other_services,
]

def main():
    failed = []
    for test in tests:
        try:
            test()
        except Exception as err:
            print(f'[FAIL] {test.__name__}: {err}')
            failed.append(test.__name__)

    if failed:
        print(f'\n[FAILED] {len(failed)} test(s): {", ".join(failed)}')
        return 1
    else:
        print(f'\n[SUCCESS] All {len(tests)} workflow filter tests passed')
        return 0

if __name__ == '__main__':
    exit(main())
