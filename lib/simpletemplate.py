import re

def eval_template(template, env):
    used = set()
    def replace_with_env(matchobj):
        var = matchobj[0]
        var = var[2:-2]
        try:
            val = env[var]
        except KeyError as e:
            raise Exception(f"unknown variable {var}") from e
        try:
            val_str = str(val)
        except Exception as e:
            raise Exception(f"env value {var!r}={val!r} cannot be made a str") from e
        used.add(var)
        return val_str
    r = re.sub(r"\{\{\S+\}\}", replace_with_env, template)
    #r = re.sub(r"\{\{\}\}", replace_with_env, template)
    if used != set(env.keys()):
        raise Exception(f"unused variable(s): {set(env.keys() - used)}")
    return r

def _test_eval_template():
    t = """{{foo}}
{{bar}} {{baz}}
"""
    env = {
        "foo": "1",
        "bar": "2",
        "baz": "10",
    }
    res = eval_template(t, env)
    assert res == """1
2 10
"""
    try:
        eval_template(t, {})
        assert false # should crash
    except Exception as e:
        assert "unknown variable" in str(e)

    try:
        eval_template(t, {"blurp": "20", **env})
        assert false #should crash
    except Exception as e:
        assert "unused variable" in str(e)

_test_eval_template()


