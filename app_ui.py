import asyncio
import datetime
import json
import os
import sys
import urllib.request
from typing import AsyncGenerator
import genshin
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ACCOUNTS_FILE = os.path.join(os.path.dirname(__file__), "accounts.json")
HTML_FILE = os.path.join(os.path.dirname(__file__), "web", "index.html")

app = FastAPI(title="HoYoLAB Multi-Account Toolkit")

GAME_MAP = {
    "GENSHIN": genshin.Game.GENSHIN,
    "STARRAIL": genshin.Game.STARRAIL,
    "ZZZ": genshin.Game.ZZZ,
}

GAME_SLUG_MAP = {
    genshin.Game.GENSHIN: "genshin",
    genshin.Game.STARRAIL: "hkrpg",
    genshin.Game.ZZZ: "nap",
}

# Các từ khóa nhận diện tài nguyên in-game cần ưu tiên giật quà
INGAME_RESOURCE_KEYWORDS = [
    "primogem", "stellar jade", "polychrome", # Tiền quay gacha
    "mora", "credit", "denny",               # Tiền vàng in-game
    "hero's wit", "adventurer", "traveler's guide", # Sách kinh nghiệm nhân vật
    "refined aether", "enhancement ore",     # Khoáng thạch/kinh nghiệm nón, vũ khí
    "battery", "fuel", "fragile resin"       # Thể lực/nhựa
]


class AccountModel(BaseModel):
    id: str
    name: str
    game: str
    ltuid_v2: str
    ltoken_v2: str
    cookie_token_v2: str = ""
    uid: int | None = None
    level: int | None = None
    mimo_points: int | None = None


def load_accounts() -> list[dict]:
    if not os.path.exists(ACCOUNTS_FILE):
        return []
    try:
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_accounts(accounts: list[dict]):
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(accounts, f, ensure_ascii=False, indent=2)


def get_genshin_client(acc: dict) -> genshin.Client:
    cookies = {
        "ltuid_v2": acc.get("ltuid_v2", ""),
        "account_id_v2": acc.get("ltuid_v2", ""),
        "ltoken_v2": acc.get("ltoken_v2", ""),
    }
    if acc.get("cookie_token_v2"):
        cookies["cookie_token_v2"] = acc["cookie_token_v2"]

    game = GAME_MAP.get(acc.get("game", "GENSHIN"), genshin.Game.GENSHIN)
    return genshin.Client(cookies, game=game, lang="vi-vn")


def fetch_public_active_codes(game: genshin.Game) -> list[dict]:
    slug = GAME_SLUG_MAP.get(game, "genshin")
    url = f"https://hoyo-codes.seria.moe/codes?game={slug}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return [item for item in data.get("codes", []) if item.get("status") == "OK"]
    except Exception:
        return []


async def fetch_mimo_codes(client: genshin.Client, game: genshin.Game) -> list[dict]:
    try:
        game_id, version_id = await client._get_mimo_game_data(game)
        history = await client.get_mimo_point_history(
            genshin.models.MimoPointOperation.EXPENSE,
            game_id=game_id,
            version_id=version_id,
            page_size=25,
        )
        return [{"code": r.code, "description": r.description} for r in history if r.code]
    except Exception:
        return []


async def redeem_single_code(client: genshin.Client, code: str, uid: int, game: genshin.Game) -> str:
    for attempt in range(3):
        try:
            await client.redeem_code(code, uid=uid, game=game)
            return "✔ NẠP THÀNH CÔNG!"
        except genshin.errors.RedemptionClaimed:
            return "ℹ Đã nhận trước đó (Already in use)"
        except genshin.errors.RedemptionInvalid:
            return "✖ Mã không hợp lệ hoặc đã hết hạn"
        except (genshin.errors.RedemptionCooldown, genshin.GenshinException) as e:
            retcode = getattr(e, "retcode", None)
            if retcode == -2018:
                return "ℹ Đã nhận trước đó"
            elif retcode == -2017:
                return "✖ Mã đã hết hạn"
            elif retcode in (-2016, -2006) or isinstance(e, genshin.errors.RedemptionCooldown):
                if attempt < 2:
                    await asyncio.sleep(6.0)
                    continue
                return "⏳ Bị Cooldown máy chủ"
            return f"✖ Lỗi [{retcode}]: {getattr(e, 'message', str(e))}"
        except Exception as e:
            return f"✖ Lỗi: {e}"
    return "✖ Không thể nạp sau 3 lần thử"


def format_sse(message: str, mtype: str = "info", done: bool = False) -> str:
    payload = json.dumps({"message": message, "type": mtype, "done": done}, ensure_ascii=False)
    return f"data: {payload}\n\n"


def is_ingame_resource(item_name: str) -> bool:
    name_lower = item_name.lower()
    return any(kw in name_lower for kw in INGAME_RESOURCE_KEYWORDS)


# ======================== FASTAPI ROUTES ========================

@app.get("/", response_class=HTMLResponse)
async def serve_home():
    if not os.path.exists(HTML_FILE):
        raise HTTPException(status_code=404, detail="Không tìm thấy web/index.html")
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        return f.read()


@app.get("/api/accounts")
async def get_all_accounts():
    return load_accounts()


@app.post("/api/accounts")
async def save_account(acc: AccountModel):
    accounts = load_accounts()
    existing_idx = next((i for i, a in enumerate(accounts) if a["id"] == acc.id), None)
    if existing_idx is not None:
        accounts[existing_idx] = acc.model_dump()
    else:
        accounts.append(acc.model_dump())
    save_accounts(accounts)
    return {"status": "ok"}


@app.delete("/api/accounts/{acc_id}")
async def remove_account(acc_id: str):
    accounts = load_accounts()
    accounts = [a for a in accounts if a["id"] != acc_id]
    save_accounts(accounts)
    return {"status": "deleted"}


@app.post("/api/accounts/{acc_id}/check")
async def check_account_info(acc_id: str):
    accounts = load_accounts()
    acc = next((a for a in accounts if a["id"] == acc_id), None)
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")

    client = get_genshin_client(acc)
    game = GAME_MAP.get(acc.get("game", "GENSHIN"), genshin.Game.GENSHIN)

    try:
        game_accs = await client.get_game_accounts()
        target_game_acc = next((a for a in game_accs if a.game == game), None)
        uid = target_game_acc.uid if target_game_acc else None
        level = target_game_acc.level if target_game_acc else None

        mimo_points = None
        try:
            mimo_points = await client.get_mimo_point_count()
        except Exception:
            pass

        acc["uid"] = uid
        acc["level"] = level
        acc["mimo_points"] = mimo_points
        save_accounts(accounts)

        return {"success": True, "uid": uid, "level": level, "mimo_points": mimo_points}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ======================== TÁC VỤ XỬ LÝ (REDEEM / MIMO / SNIPER) ========================

async def process_account_redeem(acc: dict) -> AsyncGenerator[str, None]:
    client = get_genshin_client(acc)
    game = GAME_MAP.get(acc.get("game", "GENSHIN"), genshin.Game.GENSHIN)
    name = acc["name"]

    yield format_sse(f"[{name}] Đang xác thực tài khoản...")

    try:
        game_accs = await client.get_game_accounts()
        target_game_acc = next((a for a in game_accs if a.game == game), None)
        if not target_game_acc:
            yield format_sse(f"[{name}] ✖ Không tìm thấy dữ liệu game {game.name}!", "error")
            return
        uid = target_game_acc.uid
    except Exception as e:
        yield format_sse(f"[{name}] ✖ Cookie lỗi hoặc hết hạn: {e}", "error")
        return

    mimo_codes = await fetch_mimo_codes(client, game)
    public_codes = fetch_public_active_codes(game)

    all_codes = []
    seen = set()
    for m in mimo_codes:
        c = m["code"].strip()
        if c not in seen:
            seen.add(c)
            all_codes.append({"code": c, "rewards": m["description"]})
    for p in public_codes:
        c = p["code"].strip()
        if c not in seen:
            seen.add(c)
            all_codes.append({"code": c, "rewards": p.get("rewards") or "Quà tặng sự kiện"})

    yield format_sse(f"[{name}] Tìm thấy {len(all_codes)} mã quà khả dụng. Bắt đầu nạp...")

    for i, item in enumerate(all_codes, 1):
        code = item["code"]
        rewards = item["rewards"]
        yield format_sse(f"[{name}] [{i}/{len(all_codes)}] Thử mã: {code} ({rewards})")
        
        result = await redeem_single_code(client, code, uid, game)
        mtype = "success" if "✔" in result else ("warn" if "ℹ" in result else "error")
        yield format_sse(f"[{name}] -> Kết quả: {result}", mtype)

        await asyncio.sleep(5.5)

    yield format_sse(f"[{name}] ✔ Hoàn tất nạp giftcode!", "success")


async def attempt_buy_valuables(client: genshin.Client, game_id: int, version_id: int, points: int, acc: dict) -> tuple[int, list[str]]:
    items = await client.get_mimo_shop_items(game_id=game_id, version_id=version_id)
    items = sorted(items, key=lambda x: x.cost, reverse=True)

    bought_count = 0
    logs = []

    for item in items:
        # Ưu tiên các tài nguyên in-game
        if not is_ingame_resource(item.name):
            continue

        if item.status == genshin.models.MimoShopItemStatus.EXCHANGEABLE and item.cost <= points:
            try:
                code = await client.buy_mimo_shop_item(item.id, game_id=game_id, version_id=version_id)
                points -= item.cost
                bought_count += 1
                logs.append(f"✔ ĐÃ MUA THÀNH CÔNG: {item.name}! (Mã: {code or 'Nhận ingame'})")

                if code and acc.get("cookie_token_v2"):
                    try:
                        await client.redeem_code(code)
                        logs.append(f"✔ Đã tự động kích hoạt mã {code} vào game!")
                    except Exception as err:
                        logs.append(f"ℹ Code {code} - nhập tay do: {err}")
                await asyncio.sleep(1.0)
            except Exception as e:
                logs.append(f"✖ Không thể mua {item.name}: {e}")

    return bought_count, logs


async def process_account_mimo(acc: dict) -> AsyncGenerator[str, None]:
    client = get_genshin_client(acc)
    game = GAME_MAP.get(acc.get("game", "GENSHIN"), genshin.Game.GENSHIN)
    name = acc["name"]

    yield format_sse(f"[{name}] Đang kết nối shop Mimo của {game.name}...")

    try:
        game_id, version_id = await client._get_mimo_game_data(game)
        points = await client.get_mimo_point_count()
        acc["mimo_points"] = points
        yield format_sse(f"[{name}] Điểm Mimo hiện có: {points} pts")

        # Mua các tài nguyên ingame trước
        yield format_sse(f"[{name}] Đang quét các tài nguyên in-game (Primogem, Mora, EXP...)...")
        bought_count, logs = await attempt_buy_valuables(client, game_id, version_id, points, acc)
        for log in logs:
            yield format_sse(f"[{name}] {log}", "success" if "✔" in log else "warn")

        # Quét các item còn lại (khung avatar, decor)
        items = await client.get_mimo_shop_items(game_id=game_id, version_id=version_id)
        other_bought = False
        for item in items:
            if not is_ingame_resource(item.name) and item.status == genshin.models.MimoShopItemStatus.EXCHANGEABLE and item.cost <= points:
                try:
                    code = await client.buy_mimo_shop_item(item.id, game_id=game_id, version_id=version_id)
                    points -= item.cost
                    other_bought = True
                    yield format_sse(f"[{name}] ✔ Đã nhận: {item.name}", "success")
                    await asyncio.sleep(1.0)
                except Exception:
                    pass

        if bought_count == 0 and not other_bought:
            yield format_sse(f"[{name}] Hiện tại các tài nguyên in-game đang hết hàng hoặc bạn chưa đủ điểm.")
    except Exception as e:
        yield format_sse(f"[{name}] ✖ Lỗi shop Mimo: {e}", "error")


async def process_account_sniper(acc: dict) -> AsyncGenerator[str, None]:
    """Chế độ canh giờ Restock tự động cho tất cả các tài nguyên ingame (Primogem, Mora, Exp,...)"""
    client = get_genshin_client(acc)
    game = GAME_MAP.get(acc.get("game", "GENSHIN"), genshin.Game.GENSHIN)
    name = acc["name"]

    yield format_sse(f"[{name}] 🎯 Đang phân tích thời gian Restock các tài nguyên in-game...")

    try:
        game_id, version_id = await client._get_mimo_game_data(game)
        points = await client.get_mimo_point_count()
        acc["mimo_points"] = points

        items = await client.get_mimo_shop_items(game_id=game_id, version_id=version_id)
        
        # Tìm các tài nguyên ingame và thời gian restock của chúng
        resource_items = [it for it in items if is_ingame_resource(it.name)]
        restock_times = [it.next_refresh_time for it in resource_items if it.next_refresh_time and it.next_refresh_time.total_seconds() > 0]

        yield format_sse(f"[{name}] Tìm thấy {len(resource_items)} món tài nguyên in-game (Primogem, Mora, Sách EXP...).")
        for it in resource_items:
            stock_info = f"Còn: {it.stock}" if it.stock > 0 else "Hết hàng"
            rf_info = f" | Restock sau: {it.next_refresh_time}" if it.next_refresh_time and it.next_refresh_time.total_seconds() > 0 else ""
            yield format_sse(f"[{name}] -> {it.name} ({it.cost} pts) | {stock_info}{rf_info}")

        if not restock_times:
            yield format_sse(f"[{name}] ℹ Không có lịch đếm ngược restock cụ thể trong hôm nay. Đang thử giật ngay 1 lượt...")
            b_cnt, b_logs = await attempt_buy_valuables(client, game_id, version_id, points, acc)
            for l in b_logs:
                yield format_sse(f"[{name}] {l}", "success" if "✔" in l else "warn")
            if b_cnt == 0:
                yield format_sse(f"[{name}] Hết hàng hoặc chưa tới giờ mở bán.")
            return

        earliest = min(restock_times)
        wait_seconds = earliest.total_seconds()
        target_dt = datetime.datetime.now() + earliest

        yield format_sse(f"[{name}] ⏳ Đợt Restock gần nhất: {target_dt.strftime('%H:%M:%S ngày %d/%m/%Y')} (còn {int(wait_seconds)}s)", "warn")
        yield format_sse(f"[{name}] 💤 Bot sẽ tự động thức dậy trước 5s để giật quà ngay khi mở kho...")

        # Chờ đến giờ G (trừ 5s khởi động)
        sleep_time = wait_seconds - 5.0
        if sleep_time > 0:
            while sleep_time > 0:
                step = min(sleep_time, 10.0)
                await asyncio.sleep(step)
                sleep_time -= step
                rem = (target_dt - datetime.datetime.now()).total_seconds()
                if rem > 10:
                    yield format_sse(f"[{name}] [Đếm ngược] Còn {int(rem)} giây...")

        yield format_sse(f"[{name}] ⚡ ĐÃ ĐẾN GIỜ MỞ BÁN! Bắt đầu spam yêu cầu giật tài nguyên...", "warn")

        sniper_start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - sniper_start < 90.0:
            b_cnt, b_logs = await attempt_buy_valuables(client, game_id, version_id, points, acc)
            for l in b_logs:
                yield format_sse(f"[{name}] {l}", "success")
            if b_cnt > 0:
                yield format_sse(f"[{name}] 🎉 ĐÃ GIẬT ĐƯỢC {b_cnt} MÓN TÀI NGUYÊN THÀNH CÔNG!", "success")
                break
            await asyncio.sleep(1.2)

        yield format_sse(f"[{name}] Hoàn tất đợt canh restock.")

    except Exception as e:
        yield format_sse(f"[{name}] ✖ Lỗi: {e}", "error")


# ======================== SSE STREAMING ENDPOINTS ========================

@app.get("/api/redeem/{acc_id}")
async def stream_redeem_single(acc_id: str):
    accounts = load_accounts()
    acc = next((a for a in accounts if a["id"] == acc_id), None)
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")

    async def event_generator():
        async for msg in process_account_redeem(acc):
            yield msg
        yield format_sse("Kết thúc", done=True)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/mimo/{acc_id}")
async def stream_mimo_single(acc_id: str):
    accounts = load_accounts()
    acc = next((a for a in accounts if a["id"] == acc_id), None)
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")

    async def event_generator():
        async for msg in process_account_mimo(acc):
            yield msg
        yield format_sse("Kết thúc", done=True)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/sniper/{acc_id}")
async def stream_sniper_single(acc_id: str):
    accounts = load_accounts()
    acc = next((a for a in accounts if a["id"] == acc_id), None)
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")

    async def event_generator():
        async for msg in process_account_sniper(acc):
            yield msg
        yield format_sse("Kết thúc", done=True)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/batch/redeem")
async def stream_batch_redeem():
    accounts = load_accounts()

    async def event_generator():
        yield format_sse(f"--- BẮT ĐẦU CHẠY NẠP CODE HÀNG LOẠT ({len(accounts)} TÀI KHOẢN) ---")
        for idx, acc in enumerate(accounts, 1):
            yield format_sse(f"\n===== [TÀI KHOẢN {idx}/{len(accounts)}]: {acc['name']} =====")
            async for msg in process_account_redeem(acc):
                yield msg
            await asyncio.sleep(2.0)
        yield format_sse("--- HOÀN TẤT TẤT CẢ TÀI KHOẢN ---", "success", done=True)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/batch/mimo")
async def stream_batch_mimo():
    accounts = load_accounts()

    async def event_generator():
        yield format_sse(f"--- BẮT ĐẦU QUÉT ĐỔI QUÀ MIMO ({len(accounts)} TÀI KHOẢN) ---")
        for idx, acc in enumerate(accounts, 1):
            yield format_sse(f"\n===== [TÀI KHOẢN {idx}/{len(accounts)}]: {acc['name']} =====")
            async for msg in process_account_mimo(acc):
                yield msg
            await asyncio.sleep(2.0)
        yield format_sse("--- HOÀN TẤT QUÉT SHOP TẤT CẢ TÀI KHOẢN ---", "success", done=True)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/batch/sniper")
async def stream_batch_sniper():
    accounts = load_accounts()

    async def event_generator():
        yield format_sse(f"--- BẮT ĐẦU CANH RESTOCK TÀI NGUYÊN CHO TẤT CẢ TÀI KHOẢN ---")
        for idx, acc in enumerate(accounts, 1):
            yield format_sse(f"\n===== [TÀI KHOẢN {idx}/{len(accounts)}]: {acc['name']} =====")
            async for msg in process_account_sniper(acc):
                yield msg
            await asyncio.sleep(2.0)
        yield format_sse("--- HOÀN TẤT TẤT CẢ TÀI KHOẢN ---", "success", done=True)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app_ui:app", host="127.0.0.1", port=8000, reload=False)
