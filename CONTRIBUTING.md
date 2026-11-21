# Contributing

Use synthetic profile names, hostnames and credentials in issues and examples. Run the tests from the repository root:

    ./setup.sh
    PYTHONPATH=helper .venv/bin/python -m unittest discover -s tests -v
    node --check helper/portal.js
    sh -n setup.sh murashka-helper

For incompatible wg-easy API behavior, include the upstream release number and a sanitized status code. Keep private keys and upstream response bodies out of issues. Changes to the approval boundary need tests for origin validation, wrong-password rejection and replay prevention.
