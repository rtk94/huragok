from goodbye import farewell


def test_farewell_normal_name():
    assert farewell('World') == 'Goodbye, World!'


def test_farewell_empty_string():
    assert farewell('') == 'Goodbye, !'


def test_farewell_whitespace_padded():
    assert farewell('  Alice  ') == 'Goodbye,   Alice  !'
