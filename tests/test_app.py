import os, base64, io, importlib
os.environ.update(SECRET_KEY="x", ADMIN_PASSWORD="pw", DB_PATH="/tmp/ourplay_test.db")
if os.path.exists("/tmp/ourplay_test.db"): os.remove("/tmp/ourplay_test.db")
import app as A
H={"Authorization":"Basic "+base64.b64encode(b"me:pw").decode()}

def test_setup_links_profiles_and_game():
    c=A.app.test_client()
    assert c.get("/setup").status_code==401 and c.get("/api/setup",headers={"Authorization":"Basic "+base64.b64encode(b"a:bad").decode()}).status_code==401
    ps=c.get("/api/setup",headers=H).json["players"]; t=[p["link"].rsplit("/",1)[1] for p in ps]
    r=c.post("/api/setup/0",json={"name":"Sanjay","avatar":"🐻"},headers=H); assert r.json["players"][0]["name"]=="Sanjay"
    assert c.post("/api/setup/1",json={"img":"data:image/png;base64,AAAA"},headers=H).status_code==400   # fake image rejected
    from PIL import Image; b=io.BytesIO(); Image.new("RGB",(8,8),"red").save(b,"PNG")
    assert c.post("/api/setup/1",json={"img":"data:image/png;base64,"+base64.b64encode(b.getvalue()).decode()},headers=H).status_code==200
    assert c.get("/avatar/1").mimetype=="image/png" and c.get("/avatar/0").status_code==404
    assert c.get("/p/"+t[0]).status_code==200 and c.get("/p/nope").status_code==404
    s0=A.sio.test_client(A.app,auth={"token":t[0]}); s1=A.sio.test_client(A.app,auth={"token":t[1]})
    assert not A.sio.test_client(A.app,auth={"token":"bad"}).is_connected()
    s0.get_received(); s0.emit("roll"); st=[e for e in s0.get_received() if e["name"]=="state"][-1]["args"][0]
    assert st["game"]["dice"] in range(1,7) and st["game"]["log"][-1]["n"]==st["game"]["seq"]
    wrong=s1 if st["game"]["turn"]==0 else s0   # whoever's turn it is NOT
    wrong.get_received(); wrong.emit("roll"); assert any(e["name"]=="err" for e in wrong.get_received())
    s0.emit("chat",{"t":"hi"}); assert any(e["name"]=="chat" for e in s1.get_received())
    # regenerating a link revokes the old one
    c.post("/api/setup/1",json={"regen":True},headers=H); assert c.get("/p/"+t[1]).status_code==404
    assert not A.sio.test_client(A.app,auth={"token":t[1]}).is_connected()
