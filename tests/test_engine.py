import random, engine

def play(seed):
    rng=random.Random(seed); g=engine.new_game()
    for _ in range(20000):
        if g["status"]!="playing": return g
        s=g["turn"]; engine.roll(g,s,rng)
        if g["pending"]: engine.move(g,s,rng.choice(g["legal"]))
    return g

def test_random_games_finish():
    assert all(play(i)["status"]=="won" for i in range(30))

def test_unlock_and_turn_rules():
    g=engine.new_game(); g["dice"]=1; g["pending"]=True; g["legal"]=engine.legal_moves(g,0,1)
    assert g["legal"]==[0,1,2,3]; engine.move(g,0,0); assert g["tokens"][0][0]==0 and g["turn"]==1  # 1 unlocks, no extra roll
    g=engine.new_game(); g["dice"]=6; g["pending"]=True; g["legal"]=[0]; engine.move(g,0,0); assert g["turn"]==0  # 6 = extra roll

def test_capture_gives_extra_roll_and_safe_squares():
    g=engine.new_game(); g["tokens"][0][0]=3; g["tokens"][1][0]=(3-13)%52   # blue on abs 3
    g["tokens"][0][0]=2; g["dice"]=1; g["pending"]=True; g["legal"]=[0]
    assert engine.move(g,0,0) is True and g["tokens"][1][0]==-1 and g["turn"]==0
    g=engine.new_game(); g["tokens"][0][0]=7; g["tokens"][1][0]=(8-13)%52   # blue on safe abs 8
    g["dice"]=1; g["pending"]=True; g["legal"]=[0]
    assert engine.move(g,0,0) is False and g["tokens"][1][0]==47

def test_exact_home_and_illegal():
    g=engine.new_game(); g["tokens"][0]=[55,-1,-1,-1]
    assert engine.legal_moves(g,0,2)==[] and engine.legal_moves(g,0,1)==[0,1,2,3]
    try: engine.roll(g,1); assert False
    except ValueError: pass
