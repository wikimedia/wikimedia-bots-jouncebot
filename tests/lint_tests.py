#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import yaml


def lint_yaml(path):
    try:
        obj = yaml.safe_load(open(path, 'r'))
        assert obj, "Parse failed for %s: empty result" % path
    except yaml.error.YAMLError as exc:
        assert False, "YAML parse error in %s: %s" % (path, exc)


def test_lint_DefaultConfig():
    lint_yaml(os.path.realpath(
        os.path.join(os.path.dirname(__file__), '../DefaultConfig.yaml')))
