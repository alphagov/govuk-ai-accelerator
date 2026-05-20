from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_deploy_workflow_bakes_ontology_harness_deployment_id_into_image():
    workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(
        encoding="utf-8"
    )

    assert "resolve-ontology-harness-deployment-id:" in workflow
    assert (
        'deployment_id="$(git describe --tags --exact-match 2>/dev/null || git rev-parse HEAD)"'
        in workflow
    )
    assert "needs: resolve-ontology-harness-deployment-id" in workflow
    assert "buildArgs: |" in workflow
    assert "ONTOLOGY_HARNESS_ENABLED=true" in workflow
    assert (
        "ONTOLOGY_HARNESS_DEPLOYMENT_ID="
        "${{ needs.resolve-ontology-harness-deployment-id.outputs.deployment_id }}"
        in workflow
    )


def test_dockerfile_exposes_ontology_harness_build_args_as_runtime_env():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "ARG ONTOLOGY_HARNESS_ENABLED=false" in dockerfile
    assert 'ARG ONTOLOGY_HARNESS_DEPLOYMENT_ID=""' in dockerfile
    assert "ENV ONTOLOGY_HARNESS_ENABLED=${ONTOLOGY_HARNESS_ENABLED}" in dockerfile
    assert "ENV ONTOLOGY_HARNESS_DEPLOYMENT_ID=${ONTOLOGY_HARNESS_DEPLOYMENT_ID}" in dockerfile
