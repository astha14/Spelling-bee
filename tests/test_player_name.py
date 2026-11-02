import pytest
from backend.host import Host
from backend.player_name import extract_name


@pytest.mark.parametrize("spoken, name", [
    ("Divyansh", "Divyansh"), ("My name is Divyansh.", "Divyansh"),
    ("Hi, my name is Divyansh.", "Divyansh"),
    ("Hello! I'm Divyansh.", "Divyansh"), ("I am Alex", "Alex"),
    ("MY NAME IS Alex", "Alex"), ("I'm Mary Jane", "Mary Jane"),
    ("I’m Anne-Marie", "Anne-Marie"), ("This is O'Neil", "O'Neil"),
    ("You can call me Sam", "Sam"), ("Hina", "Hina"),
])
def test_name_without_introduction(spoken, name):
    assert extract_name(spoken) == name
    host = Host()
    host.begin()
    response = host.handle(spoken)
    assert response.startswith(f"Hi, {name}!")
    assert host.name == name


def test_empty_introduction_asks_for_name_again():
    host = Host()
    host.begin()
    assert host.handle("Hi, my name is.") == "What is your name?"


def test_letters_are_not_sent_to_frontend():
    host = Host()
    host.letters = "ABC"
    assert "letters" not in host.state()
