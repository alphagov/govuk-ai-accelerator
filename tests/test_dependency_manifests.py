from pathlib import Path
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_declares_faiss_cpu_dependency():
    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text())

    dependencies = pyproject["project"]["dependencies"]

    assert any(dependency.startswith("faiss-cpu") for dependency in dependencies)


def test_requirements_txt_declares_faiss_cpu_dependency():
    requirements_path = PROJECT_ROOT / "requirements.txt"
    dependencies = [
        line.strip()
        for line in requirements_path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    assert any(dependency.startswith("faiss-cpu") for dependency in dependencies)
