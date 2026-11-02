from backend.host import Host

def ready():
    host = Host()
    host.begin()
    host.handle("Alex")
    host.handle("easy mode")
    return host

def test_pauses_and_confirmation():
    h = ready()
    word = h.game.current.text
    for letter in word:
        assert h.handle(letter) == ""
    assert h.game.index == 0
    h.handle(action="submit")
    assert h.game.index == 0
    h.handle(action="confirm")
    assert h.game.score == 10
    assert h.game.index == 1

def test_retry_and_unrelated_speech():
    h = ready()
    h.handle("B B")
    h.handle("I love this game")
    assert h.letters == "BB"
    h.handle(action="submit")
    h.handle(action="clear")
    assert h.letters == ""
    assert h.game.index == 0

def test_repeat_does_not_leak_in_state():
    h = ready()
    assert h.game.current.text in h.handle(action="repeat")
    assert h.game.current.text not in str(h.state())

def test_no_double_grading():
    h = ready()
    h.handle("Z")
    h.handle(action="submit")
    h.handle(action="confirm")
    h.handle(action="confirm")
    assert h.game.index == 1


def test_entire_game_and_replay_using_only_speech():
    from backend.host import Phase
    h = Host()
    assert h.phase == Phase.IDLE
    h.begin()
    h.handle("start game")
    h.handle("easy mode")
    for index in range(10):
        h.handle(" ".join(h.game.current.text.upper()))
        h.handle("finished")
        assert h.game.index == index
        h.handle("confirm")
        assert h.game.index == index + 1
    assert h.phase == Phase.GAME_OVER
    assert h.game.score == 100
    for phase in Phase:
        assert phase in h.transitions
    h.handle("play again")
    assert h.phase == Phase.DIFFICULTY_SELECTION
    assert h.game.score == 0
    h.handle("hard mode")
    assert h.phase == Phase.SPELLING
    assert h.difficulty == "hard"


def test_corrections_and_commands_preserve_score():
    h = ready()
    h.handle("A B C")
    h.handle("replace last letter with D")
    assert h.letters == "ABD"
    h.handle("done")
    h.handle("undo")
    assert h.letters == "AB"
    assert h.pending is None
    for command in ["repeat the word", "give me a hint", "use it in a sentence", "what does it mean?", "what's my score?", "next word"]:
        assert h.handle(command)
        assert h.letters == "AB"
        assert h.game.index == 0
    h.handle("let me try again")
    assert h.letters == ""


def test_ambiguous_segment_is_not_appended_or_graded():
    h = ready()
    h.handle("C A")
    assert h.handle("B for dog")
    assert h.letters == "CA"
    assert h.game.index == 0


def test_end_and_restart_before_name():
    h = Host()
    h.begin()
    h.handle("end game")
    assert h.state()["finished"]
    h.handle("play again")
    h.handle("medium mode")
    assert not h.state()["finished"]


def test_unclear_letters_followed_by_done_do_not_submit_previous_buffer():
    h = ready()
    h.handle("A B")
    h.handle("C or D, done")
    assert h.letters == "AB"
    assert h.pending is None
    assert h.game.index == 0
