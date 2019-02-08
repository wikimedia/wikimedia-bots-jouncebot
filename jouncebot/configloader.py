# -*- coding: utf-8 -*-
import yaml

values = {}


def construct_yaml_str(self, node):
    """Create unicode objects for YAML string nodes."""
    # From http://stackoverflow.com/a/2967461/8171
    return self.construct_scalar(node)


# Attach custom unicode factory to string events
yaml.Loader.add_constructor('tag:yaml.org,2002:str', construct_yaml_str)
yaml.SafeLoader.add_constructor('tag:yaml.org,2002:str', construct_yaml_str)


def import_file(filename):
    """Update the values object with the contents from a YAML configuration
    file.

    :param string filename: Name of the file to import

    :throws IOError
    :throws yaml.ParserError
    """
    global values
    values = _merge(yaml.load(open(filename, 'r')), values)


def _merge(new_vals, existing_obj):
    if isinstance(new_vals, dict) and isinstance(existing_obj, dict):
        for k, v in list(existing_obj.items()):
            if k not in new_vals:
                new_vals[k] = v
            else:
                new_vals[k] = _merge(new_vals[k], v)
    return new_vals
