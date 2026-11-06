# -*- coding: utf-8 -*-
"""가짜 Ollama 서버

nk 가 쓰는 것만: POST /api/chat (검수 질문·계획표 쓰기), POST /api/generate (모델 내리기 keep_alive 0),
GET /api/tags, GET /api/ps, POST /api/pull.

답 만들기 — nk 질문 글에서 질문 id 와 보기를 읽어서 JSON 한 개로 답함:
  '"id": 질문  Options: a | b | c'      -> 보기 하나
  '"id": 질문  (answer true or false)'   -> true / false
  '"f1": 문장' (이야기 검사 statement)  -> true / false
  '"eyes": one of "x", "y"'             (얼굴 깨짐 질문) -> 보기 하나
mode (스위치):
  pass = 합격 답: 캐릭터 파일(characters/*.yaml)의 expect 에 맞는 보기, 없으면 첫 보기 / true
  fail = 불합격 답: expect 에 안 맞는 보기(마지막 쪽) / false
  mixed = 질문마다 번갈아 (id 이름 해시로 고정)
  garbage = JSON 이 아닌 말 (검수 AI 가 이상한 답을 할 때)
  error = HTTP 500
바꾸기: 실행할 때 --mode, 또는 도는 중에 POST /mock/mode {"mode": "fail"}

실행:  python tests/mock_ollama.py --port 18434 --mode pass"""
import os, sys, re, json, glob, time, hashlib, argparse, threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_expect(kit=KIT):
    """characters/*.yaml qa_checklist 의 {id: [expect...]}"""
    out = {}
    try:
        import yaml
    except ImportError:
        return out
    for p in glob.glob(os.path.join(os.environ.get("NK_CHARS") or os.path.join(kit, "characters"), "*.yaml")):
        try:
            d = yaml.safe_load(open(p, encoding="utf-8")) or {}
        except Exception:
            continue
        for it in d.get("qa_checklist") or []:
            if isinstance(it, dict) and it.get("id") and it.get("expect"):
                out.setdefault(str(it["id"]), [str(e).lower() for e in it["expect"]])
    return out


def parse_questions(prompt):
    """[(id, 종류, 보기 목록)]  종류 = options / bool"""
    qs, seen = [], set()
    for line in prompt.splitlines():
        m = re.match(r'\s*"([^"]+)":\s*(.*)$', line)
        if not m:
            continue
        qid, rest = m.group(1), m.group(2)
        if qid in seen:
            continue
        seen.add(qid)
        mo = re.search(r"Options:\s*(.+)$", rest)
        if mo:
            qs.append((qid, "options", [o.strip() for o in mo.group(1).split("|") if o.strip()]))
            continue
        m1 = re.match(r"one of (.+)$", rest.strip())
        if m1:
            qs.append((qid, "options", re.findall(r'"([^"]+)"', m1.group(1))))
            continue
        qs.append((qid, "bool", []))
    return qs


def answer(prompt, mode, expect):
    qs = parse_questions(prompt)
    out = {}
    for qid, kind, opts in qs:
        m = mode
        if mode == "mixed":
            m = "pass" if int(hashlib.md5(qid.encode()).hexdigest(), 16) % 2 == 0 else "fail"
        if kind == "bool":
            out[qid] = (m == "pass")
            continue
        exp = expect.get(qid) or []
        good = [o for o in opts if any(e in o.lower() for e in exp)] if exp else opts[:1]
        bad = [o for o in opts if o not in good]
        if m == "pass":
            out[qid] = (good or opts or [""])[0]
        else:
            # 불합격: 기대와 다른 보기 중 '안 보임' 이 아닌 것 (안 보임은 합격 처리되는 항목이 있음)
            nb = [o for o in bad if "not visible" not in o.lower()] or bad or opts
            out[qid] = nb[-1] if nb else ""
    return out, qs


class State:
    def __init__(self, mode):
        self.mode = mode
        self.expect = load_expect()
        self.log = []
        self.lock = threading.Lock()


def make_handler(S):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body):
            b = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if self.path.startswith("/api/tags"):
                return self._send(200, {"models": [{"name": "gemma4:e4b-it-qat", "size": 6100000000}]})
            if self.path.startswith("/api/ps"):
                return self._send(200, {"models": []})
            if self.path.startswith("/mock/log"):
                with S.lock:
                    return self._send(200, {"mode": S.mode, "log": S.log})
            if self.path == "/":
                return self._send(200, "Ollama is running")
            return self._send(404, {"error": "mock: unknown path"})

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                d = json.loads(self.rfile.read(n).decode("utf-8") or "{}") if n else {}
            except Exception:
                return self._send(400, {"error": "bad json"})
            if self.path == "/mock/mode":
                S.mode = d.get("mode", S.mode)
                return self._send(200, {"mode": S.mode})
            if self.path == "/api/generate":
                with S.lock:
                    S.log.append((time.time(), "generate", d.get("keep_alive")))
                return self._send(200, {"model": d.get("model"), "response": "", "done": True, "done_reason": "unload"})
            if self.path == "/api/pull":
                return self._send(200, {"status": "success"})
            if self.path != "/api/chat":
                return self._send(404, {"error": "mock: unknown path " + self.path})
            if S.mode == "error":
                return self._send(500, {"error": "mock error mode"})
            msgs = d.get("messages") or []
            prompt = "\n".join(str(m.get("content", "")) for m in msgs if m.get("role") == "user")
            n_img = sum(len(m.get("images") or []) for m in msgs)
            if S.mode == "garbage":
                content = "I think the picture looks nice."
                qs = []
            else:
                ans, qs = answer(prompt, S.mode, S.expect)
                content = json.dumps(ans, ensure_ascii=False) if qs else "{}"
            with S.lock:
                S.log.append((time.time(), "chat", {"mode": S.mode, "questions": [q[0] for q in qs], "images": n_img}))
            return self._send(200, {"model": d.get("model"), "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    "message": {"role": "assistant", "content": content}, "done": True,
                                    "prompt_eval_count": len(prompt) // 4, "eval_count": len(content) // 4})
    return H


def serve(port, mode="pass", host="127.0.0.1"):
    S = State(mode)
    srv = ThreadingHTTPServer((host, port), make_handler(S))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, S


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--port", type=int, default=18434)
    a.add_argument("--mode", default="pass", choices=["pass", "fail", "mixed", "garbage", "error"])
    o = a.parse_args()
    srv, _ = serve(o.port, o.mode)
    print("mock Ollama on http://127.0.0.1:%d  mode=%s" % (o.port, o.mode))
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
