from hello import greet


def test_greet_normal_name():
    assert greet('World') == 'Hello, World!'


def test_greet_empty_string():
    assert greet('') == 'Hello, !'


def test_greet_whitespace_padded():
    assert greet('  Alice  ') == 'Hello,   Alice  !'
