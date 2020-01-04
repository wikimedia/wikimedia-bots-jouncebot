# -*- coding: utf-8 -*-
"""Tests."""
import os

import yaml


def lint_yaml(path):
    """Check YAML file for errors."""
    try:
        obj = yaml.safe_load(open(path, "r"))
        assert obj, "Parse failed for %s: empty result" % path
    except yaml.error.YAMLError as exc:
        raise AssertionError("YAML parse error in %s: %s" % (path, exc))


def test_lint_DefaultConfig():
    """Lint the default config."""
    lint_yaml(
        os.path.realpath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "etc",
                "DefaultConfig.yaml",
            )
        )
    )
