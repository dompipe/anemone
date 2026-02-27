from setuptools import setup, find_packages

setup(
    name='ollama-nlp-engine',
    version='0.1.0',
    description='Modular, context-aware NLP and code engine with subject-specific blending and algebraic solving.',
    author='Your Name',
    packages=find_packages(),
    install_requires=[
        'sympy',
        'fastapi',
        'uvicorn[standard]',
        'pydantic',
    ],
    python_requires='>=3.7',
    entry_points={
        'console_scripts': [
            'anemone = anemone_agent.cli:main',
            'ollama-shell = shell:main',
            'patch-kingdom-json = scripts.patch_kingdom_json:main',
            'pending-patches = scripts.pending_patches_cli:main',
            'kingdom-editor = scripts.kingdom_editor:main',
        ],
    },
    include_package_data=True,
    zip_safe=False,
)
