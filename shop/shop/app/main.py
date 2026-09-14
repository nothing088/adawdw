import io
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from bson import ObjectId
from fastapi import (
    FastAPI,
    Request,
    HTTPException,
    UploadFile,
    File,
    Depends,
)
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import (
    init_db,
    close_db,
    users,
    categories,
    products,
    orders,
    promos,
    delivery,
    support,
    events,
    fs_bucket,
)
from .auth import current_user, admin_user
from .bot import bot, dp, configure_webhook
from .payments import create_payment, get_payment
from .notifications import notify_status, notify_admins


app = FastAPI(title="Telegram Shop — Render + MongoDB")
app.mount("/static", StaticFiles(directory="frontend"), name="static")


def now():
    return datetime.now(timezone.utc)


def money(value):
    return float(
        Decimal(str(value)).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
    )


def oid(value: str):
    try:
        return ObjectId(value)
    except Exception:
        raise HTTPException(400, "Invalid id")


@app.on_event("startup")
async def startup():
    await init_db()
    await configure_webhook()

    if await products.count_documents({}) == 0:
        await products.insert_one({
            "name": "Пример товара",
            "description": "Замените этот товар в админке.",
            "price": 990.0,
            "stock": 100,
            "image_file_id": None,
            "active": True,
            "created_at": now(),
        })

    if await delivery.count_documents({}) == 0:
        await delivery.insert_many([
            {"name": "Самовывоз", "price": 0.0, "active": True},
            {"name": "Курьер", "price": 300.0, "active": True},
        ])


@app.on_event("shutdown")
async def shutdown():
    await bot.delete_webhook(drop_pending_updates=False)
    await bot.session.close()
    await close_db()


@app.get("/")
async def index():
    return FileResponse("frontend/index.html")


@app.get("/health")
async def health():
    from .db import client
    await client.admin.command("ping")
    return {"ok": True}


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    from aiogram.types import Update
    data = await request.json()
    update = Update.model_validate(data, context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"ok": True}


@app.get("/api/me")
async def me(user=Depends(current_user)):
    tg_id = int(user["id"])
    await users.update_one(
        {"tg_id": tg_id},
        {"$set": {
            "tg_id": tg_id,
            "username": user.get("username", ""),
            "first_name": user.get("first_name", ""),
            "last_name": user.get("last_name", ""),
            "updated_at": now(),
        }},
        upsert=True,
    )
    return user


@app.get("/api/catalog")
async def catalog(q: str = "", category_id: str = ""):
    query = {"active": True}
    if category_id:
        query["category_id"] = category_id

    if q.strip():
        query["$or"] = [
            {"name": {"$regex": q.strip(), "$options": "i"}},
            {"description": {"$regex": q.strip(), "$options": "i"}},
        ]

    result_products = []
    async for p in products.find(query).sort("created_at", -1):
        result_products.append({
            "id": str(p["_id"]),
            "name": p["name"],
            "description": p.get("description", ""),
            "price": p["price"],
            "stock": p.get("stock", 0),
            "image_url": f'/api/images/{p["image_file_id"]}' if p.get("image_file_id") else "",
            "category_id": p.get("category_id", ""),
        })

    result_categories = []
    async for c in categories.find({}).sort("name", 1):
        result_categories.append({
            "id": str(c["_id"]),
            "name": c["name"],
        })

    result_delivery = []
    async for d in delivery.find({"active": True}).sort("price", 1):
        result_delivery.append({
            "id": str(d["_id"]),
            "name": d["name"],
            "price": d["price"],
        })

    return {
        "products": result_products,
        "categories": result_categories,
        "delivery": result_delivery,
    }


@app.get("/api/images/{file_id}")
async def get_image(file_id: str):
    from .db import fs_bucket
    if fs_bucket is None:
        raise HTTPException(503, "Storage not ready")

    try:
        stream = await fs_bucket.open_download_stream(ObjectId(file_id))
    except Exception:
        raise HTTPException(404, "Image not found")

    data = await stream.read()
    content_type = getattr(stream, "metadata", None)
    mime = "image/jpeg"
    if content_type and isinstance(content_type, dict):
        mime = content_type.get("content_type", mime)

    return Response(content=data, media_type=mime)


@app.get("/api/orders")
async def my_orders(user=Depends(current_user)):
    result = []
    async for o in orders.find(
        {"tg_id": int(user["id"])}
    ).sort("created_at", -1):
        result.append({
            "order_id": o["order_id"],
            "status": o["status"],
            "total": o["total"],
            "created_at": o["created_at"].isoformat(),
            "items": o["items"],
            "delivery_name": o.get("delivery_name"),
        })
    return result


@app.get("/api/orders/{order_id}")
async def my_order(order_id: str, user=Depends(current_user)):
    o = await orders.find_one({
        "order_id": order_id,
        "tg_id": int(user["id"]),
    })
    if not o:
        raise HTTPException(404, "Order not found")

    o["_id"] = str(o["_id"])
    return {
        "order_id": o["order_id"],
        "status": o["status"],
        "total": o["total"],
        "subtotal": o["subtotal"],
        "delivery_price": o["delivery_price"],
        "discount": o["discount"],
        "items": o["items"],
        "delivery_name": o.get("delivery_name"),
        "city": o.get("city", ""),
        "street": o.get("street", ""),
        "house": o.get("house", ""),
        "apartment": o.get("apartment", ""),
        "postal_code": o.get("postal_code", ""),
        "comment": o.get("comment", ""),
        "created_at": o["created_at"].isoformat(),
    }


@app.post("/api/orders")
async def create_order(payload: dict, user=Depends(current_user)):
    cart = payload.get("items") or []
    if not cart:
        raise HTTPException(400, "Корзина пуста")

    tg_id = int(user["id"])
    product_ids = []
    quantities = {}

    for line in cart:
        try:
            pid = ObjectId(line["product_id"])
        except Exception:
            raise HTTPException(400, "Некорректный товар")
        qty = int(line.get("quantity", 1))
        if qty < 1:
            raise HTTPException(400, "Некорректное количество")
        product_ids.append(pid)
        quantities[str(pid)] = quantities.get(str(pid), 0) + qty

    found = {}
    async for p in products.find({
        "_id": {"$in": product_ids},
        "active": True,
    }):
        found[str(p["_id"])] = p

    items = []
    subtotal = 0.0

    for pid, qty in quantities.items():
        p = found.get(pid)
        if not p:
            raise HTTPException(400, "Товар больше недоступен")
        if qty > int(p.get("stock", 0)):
            raise HTTPException(
                400,
                f'Недостаточный остаток: {p["name"]}',
            )

        total = money(float(p["price"]) * qty)
        subtotal += total

        items.append({
            "product_id": pid,
            "name": p["name"],
            "price": float(p["price"]),
            "quantity": qty,
            "total": total,
        })

    delivery_id = payload.get("delivery_id")
    delivery_doc = None
    if delivery_id:
        delivery_doc = await delivery.find_one({
            "_id": oid(delivery_id),
            "active": True,
        })

    delivery_price = money(
        delivery_doc["price"] if delivery_doc else 0
    )

    promo_code = (payload.get("promo_code") or "").strip().upper()
    discount = 0.0

    if promo_code:
        promo = await promos.find_one({
            "code": promo_code,
            "active": True,
        })
        if promo:
            expires_at = promo.get("expires_at")
            valid_time = not expires_at or expires_at > now()
            max_uses = promo.get("max_uses")
            valid_uses = not max_uses or promo.get("uses", 0) < max_uses
            min_order = float(promo.get("min_order", 0))

            if valid_time and valid_uses and subtotal >= min_order:
                discount = money(
                    subtotal * float(promo.get("percent", 0)) / 100
                )

    total = max(
        0.0,
        money(subtotal + delivery_price - discount),
    )

    email = (payload.get("email") or "").strip().lower()
    if settings.YOOKASSA_RECEIPT_ENABLED and not email:
        raise HTTPException(
            400,
            "Укажите email — он нужен для электронного чека.",
        )

    order_id = uuid.uuid4().hex[:12].upper()

    order = {
        "order_id": order_id,
        "tg_id": tg_id,
        "username": user.get("username", ""),
        "status": "waiting_payment",
        "payment_status": "pending",
        "items": items,
        "subtotal": subtotal,
        "delivery_price": delivery_price,
        "discount": discount,
        "total": total,
        "promo_code": promo_code or None,
        "delivery_name": delivery_doc["name"] if delivery_doc else None,
        "city": payload.get("city", ""),
        "street": payload.get("street", ""),
        "house": payload.get("house", ""),
        "apartment": payload.get("apartment", ""),
        "postal_code": payload.get("postal_code", ""),
        "comment": payload.get("comment", ""),
        "customer_email": email,
        "created_at": now(),
        "updated_at": now(),
    }

    await orders.insert_one(order)

    try:
        payment = await create_payment(order)
    except Exception as exc:
        await orders.delete_one({"order_id": order_id})
        raise HTTPException(502, f"Ошибка ЮKassa: {exc}")

    await orders.update_one(
        {"order_id": order_id},
        {"$set": {
            "payment_id": payment["id"],
            "payment_status": payment.get("status", "pending"),
        }},
    )

    await notify_admins(
        f"🛒 Новый заказ #{order_id}\n"
        f"Сумма: {total:.2f} ₽"
    )

    return {
        "order_id": order_id,
        "payment_id": payment["id"],
        "confirmation_url": payment["confirmation"]["confirmation_url"],
    }


@app.get("/api/payment/{payment_id}")
async def payment_status(
    payment_id: str,
    user=Depends(current_user),
):
    order = await orders.find_one({
        "payment_id": payment_id,
        "tg_id": int(user["id"]),
    })
    if not order:
        raise HTTPException(404, "Payment not found")

    payment = await get_payment(payment_id)

    return {
        "order_id": order["order_id"],
        "status": payment.get("status"),
        "paid": payment.get("paid", False),
    }


@app.post("/api/payments/yookassa")
async def yookassa_webhook(request: Request):
    event = await request.json()

    if event.get("event") != "payment.succeeded":
        return {"ok": True}

    obj = event.get("object") or {}
    payment_id = obj.get("id")
    if not payment_id:
        return {"ok": True}

    order = await orders.find_one({"payment_id": payment_id})
    if not order:
        return {"ok": True}

    # Idempotency: only the first webhook can move waiting_payment -> paid.
    result = await orders.update_one(
        {
            "_id": order["_id"],
            "status": {"$in": ["waiting_payment", "new"]},
        },
        {"$set": {
            "status": "paid",
            "payment_status": "succeeded",
            "paid_at": now(),
            "updated_at": now(),
        }},
    )

    if result.modified_count == 0:
        return {"ok": True}

    # Stock decrement is guarded by the successful payment transition above.
    for item in order["items"]:
        await products.update_one(
            {
                "_id": ObjectId(item["product_id"]),
                "stock": {"$gte": int(item["quantity"])},
            },
            {"$inc": {"stock": -int(item["quantity"])}},
        )

    if order.get("promo_code"):
        await promos.update_one(
            {"code": order["promo_code"]},
            {"$inc": {"uses": 1}},
        )

    await notify_status(
        order["tg_id"],
        order["order_id"],
        "paid",
    )

    return {"ok": True}


# ---------------- ADMIN ----------------

@app.get("/api/admin/stats")
async def admin_stats(_: dict = Depends(admin_user)):
    revenue = 0.0
    async for row in orders.find({
        "status": {"$in": ["paid", "processing", "shipped", "delivered"]}
    }, {"total": 1}):
        revenue += float(row.get("total", 0))

    return {
        "products": await products.count_documents({"active": True}),
        "orders": await orders.count_documents({}),
        "paid": await orders.count_documents({"status": "paid"}),
        "revenue": money(revenue),
        "support": await support.count_documents({"status": "open"}),
    }


@app.get("/api/admin/products")
async def admin_products(_: dict = Depends(admin_user)):
    result = []
    async for p in products.find({}).sort("created_at", -1):
        result.append({
            "id": str(p["_id"]),
            "name": p["name"],
            "description": p.get("description", ""),
            "price": p["price"],
            "stock": p.get("stock", 0),
            "active": p.get("active", True),
            "category_id": p.get("category_id", ""),
            "image_url": f'/api/images/{p["image_file_id"]}' if p.get("image_file_id") else "",
        })
    return result


@app.post("/api/admin/products")
async def admin_add_product(
    payload: dict,
    _: dict = Depends(admin_user),
):
    if not payload.get("name"):
        raise HTTPException(400, "Название обязательно")

    result = await products.insert_one({
        "name": payload["name"].strip(),
        "description": payload.get("description", ""),
        "price": money(payload.get("price", 0)),
        "stock": int(payload.get("stock", 0)),
        "active": bool(payload.get("active", True)),
        "category_id": payload.get("category_id", ""),
        "image_file_id": payload.get("image_file_id"),
        "created_at": now(),
    })

    return {"id": str(result.inserted_id)}


@app.put("/api/admin/products/{product_id}")
async def admin_edit_product(
    product_id: str,
    payload: dict,
    _: dict = Depends(admin_user),
):
    update = {}

    for key in ["name", "description", "active", "category_id", "image_file_id"]:
        if key in payload:
            update[key] = payload[key]

    if "price" in payload:
        update["price"] = money(payload["price"])
    if "stock" in payload:
        update["stock"] = int(payload["stock"])

    await products.update_one(
        {"_id": oid(product_id)},
        {"$set": update},
    )
    return {"ok": True}


@app.delete("/api/admin/products/{product_id}")
async def admin_delete_product(
    product_id: str,
    _: dict = Depends(admin_user),
):
    await products.update_one(
        {"_id": oid(product_id)},
        {"$set": {"active": False}},
    )
    return {"ok": True}


@app.post("/api/admin/upload")
async def admin_upload(
    file: UploadFile = File(...),
    _: dict = Depends(admin_user),
):
    allowed = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }

    if file.content_type not in allowed:
        raise HTTPException(
            400,
            "Разрешены только JPG, PNG и WEBP",
        )

    data = await file.read()

    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(400, "Максимальный размер — 8 MB")

    from .db import fs_bucket

    file_id = await fs_bucket.upload_from_stream(
        f"{uuid.uuid4().hex}.{allowed[file.content_type]}",
        io.BytesIO(data),
        metadata={"content_type": file.content_type},
    )

    return {"file_id": str(file_id)}


@app.get("/api/admin/orders")
async def admin_orders(
    q: str = "",
    status: str = "",
    _: dict = Depends(admin_user),
):
    query = {}

    if status:
        query["status"] = status

    if q.strip():
        query["$or"] = [
            {"order_id": {"$regex": q.strip(), "$options": "i"}},
            {"username": {"$regex": q.strip(), "$options": "i"}},
            {"customer_email": {"$regex": q.strip(), "$options": "i"}},
        ]

    result = []
    async for o in orders.find(query).sort("created_at", -1).limit(500):
        result.append({
            "order_id": o["order_id"],
            "tg_id": o["tg_id"],
            "username": o.get("username", ""),
            "status": o["status"],
            "payment_status": o.get("payment_status", ""),
            "total": o["total"],
            "items": o["items"],
            "delivery_name": o.get("delivery_name"),
            "city": o.get("city", ""),
            "street": o.get("street", ""),
            "house": o.get("house", ""),
            "apartment": o.get("apartment", ""),
            "postal_code": o.get("postal_code", ""),
            "customer_email": o.get("customer_email", ""),
            "comment": o.get("comment", ""),
            "created_at": o["created_at"].isoformat(),
        })
    return result


@app.put("/api/admin/orders/{order_id}/status")
async def admin_change_status(
    order_id: str,
    payload: dict,
    _: dict = Depends(admin_user),
):
    status = payload.get("status")
    allowed = {
        "new",
        "waiting_payment",
        "paid",
        "processing",
        "shipped",
        "delivered",
        "cancelled",
    }

    if status not in allowed:
        raise HTTPException(400, "Invalid status")

    order = await orders.find_one({"order_id": order_id})
    if not order:
        raise HTTPException(404, "Order not found")

    await orders.update_one(
        {"_id": order["_id"]},
        {"$set": {"status": status, "updated_at": now()}},
    )

    await notify_status(
        order["tg_id"],
        order_id,
        status,
    )

    return {"ok": True}


@app.get("/api/admin/categories")
async def admin_categories(_: dict = Depends(admin_user)):
    result = []
    async for c in categories.find({}).sort("name", 1):
        result.append({
            "id": str(c["_id"]),
            "name": c["name"],
        })
    return result


@app.post("/api/admin/categories")
async def admin_add_category(
    payload: dict,
    _: dict = Depends(admin_user),
):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Название обязательно")
    result = await categories.insert_one({
        "name": name,
        "created_at": now(),
    })
    return {"id": str(result.inserted_id)}


@app.get("/api/admin/delivery")
async def admin_delivery(_: dict = Depends(admin_user)):
    result = []
    async for d in delivery.find({}).sort("price", 1):
        result.append({
            "id": str(d["_id"]),
            "name": d["name"],
            "price": d["price"],
            "active": d.get("active", True),
        })
    return result


@app.post("/api/admin/delivery")
async def admin_add_delivery(
    payload: dict,
    _: dict = Depends(admin_user),
):
    result = await delivery.insert_one({
        "name": payload["name"].strip(),
        "price": money(payload.get("price", 0)),
        "active": True,
    })
    return {"id": str(result.inserted_id)}


@app.put("/api/admin/delivery/{delivery_id}")
async def admin_edit_delivery(
    delivery_id: str,
    payload: dict,
    _: dict = Depends(admin_user),
):
    update = {}
    if "name" in payload:
        update["name"] = payload["name"].strip()
    if "price" in payload:
        update["price"] = money(payload["price"])
    if "active" in payload:
        update["active"] = bool(payload["active"])

    await delivery.update_one(
        {"_id": oid(delivery_id)},
        {"$set": update},
    )
    return {"ok": True}


@app.get("/api/admin/promos")
async def admin_promos(_: dict = Depends(admin_user)):
    result = []
    async for p in promos.find({}).sort("code", 1):
        result.append({
            "id": str(p["_id"]),
            "code": p["code"],
            "percent": p.get("percent", 0),
            "max_uses": p.get("max_uses"),
            "uses": p.get("uses", 0),
            "min_order": p.get("min_order", 0),
            "active": p.get("active", True),
            "expires_at": p.get("expires_at").isoformat() if p.get("expires_at") else None,
        })
    return result


@app.post("/api/admin/promos")
async def admin_add_promo(
    payload: dict,
    _: dict = Depends(admin_user),
):
    code = (payload.get("code") or "").strip().upper()
    if not code:
        raise HTTPException(400, "Code required")

    expires_at = None
    if payload.get("expires_at"):
        expires_at = datetime.fromisoformat(
            payload["expires_at"].replace("Z", "+00:00")
        )

    await promos.insert_one({
        "code": code,
        "percent": float(payload.get("percent", 0)),
        "max_uses": int(payload["max_uses"]) if payload.get("max_uses") else None,
        "uses": 0,
        "min_order": float(payload.get("min_order", 0)),
        "active": True,
        "expires_at": expires_at,
        "created_at": now(),
    })
    return {"ok": True}


@app.get("/api/admin/support")
async def admin_support(_: dict = Depends(admin_user)):
    result = []
    async for s in support.find({}).sort("created_at", -1).limit(500):
        result.append({
            "id": str(s["_id"]),
            "tg_id": s["tg_id"],
            "username": s.get("username", ""),
            "message": s["message"],
            "status": s.get("status", "open"),
            "created_at": s["created_at"].isoformat(),
        })
    return result


@app.post("/api/support")
async def user_support(
    payload: dict,
    user=Depends(current_user),
):
    message = (payload.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "Сообщение пустое")

    await support.insert_one({
        "tg_id": int(user["id"]),
        "username": user.get("username", ""),
        "message": message[:4000],
        "status": "open",
        "created_at": now(),
    })

    await notify_admins(
        f"💬 Новое обращение\n"
        f"Пользователь: @{user.get('username', '')}\n"
        f"{message[:1000]}"
    )

    return {"ok": True}
