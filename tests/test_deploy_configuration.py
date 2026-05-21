from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_deploy_workflow_keys_harness_to_generator_sha():
    workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(
        encoding="utf-8"
    )

    assert "resolve-ontology-harness-generator:" in workflow
    assert "repository: alphagov/govuk-ai-accelerator-tw-accelerator" in workflow
    assert "token: ${{ secrets.GOVUK_CI_GITHUB_API_TOKEN }}" in workflow
    assert 'generator_sha="$(git -C generator rev-parse HEAD)"' in workflow
    assert 'deployment_id="tw-accelerator-${generator_sha}"' in workflow
    assert "needs: resolve-ontology-harness-generator" in workflow
    assert "buildArgs: |" in workflow
    assert (
        "GENERATOR_GIT_REF="
        "${{ needs.resolve-ontology-harness-generator.outputs.generator_sha }}"
        in workflow
    )
    assert "ONTOLOGY_HARNESS_ENABLED=true" in workflow
    assert (
        "ONTOLOGY_HARNESS_DEPLOYMENT_ID="
        "${{ needs.resolve-ontology-harness-generator.outputs.deployment_id }}"
        in workflow
    )


def test_dockerfile_exposes_ontology_harness_build_args_as_runtime_env():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "ARG ONTOLOGY_HARNESS_ENABLED=false" in dockerfile
    assert 'ARG ONTOLOGY_HARNESS_DEPLOYMENT_ID=""' in dockerfile
    assert "ARG GENERATOR_GIT_REF=main" in dockerfile
    assert "ENV ONTOLOGY_HARNESS_ENABLED=${ONTOLOGY_HARNESS_ENABLED}" in dockerfile
    assert "ENV ONTOLOGY_HARNESS_DEPLOYMENT_ID=${ONTOLOGY_HARNESS_DEPLOYMENT_ID}" in dockerfile
    assert (
        'uv pip install --system "git+https://github.com/alphagov/'
        'govuk-ai-accelerator-tw-accelerator@${GENERATOR_GIT_REF}"'
        in dockerfile
    )
