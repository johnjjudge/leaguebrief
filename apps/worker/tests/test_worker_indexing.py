from function_app import app


def test_worker_function_is_indexed():
    functions = app.get_functions()

    assert [function.get_function_name() for function in functions] == ["import_job_placeholder"]
