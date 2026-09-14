# Telegram Shop — FINAL / Render + MongoDB Atlas

Это production-oriented сборка: один Render Web Service, MongoDB Atlas, Telegram Mini App, Telegram webhook, YooKassa, GridFS для фотографий, админка.

## Что уже сделано

- FastAPI
- aiogram 3
- Telegram webhook вместо polling
- Telegram Mini App
- MongoDB Atlas через async PyMongo
- GridFS: фотографии хранятся в MongoDB, а не на эфемерном диске Render
- товары / остатки / категории
- корзина
- оформление заказа
- доставка
- промокоды с max uses / min order / сроком
- история и детали заказов
- статусы заказов
- уведомления покупателю
- поддержка
- админка
- поиск заказов
- YooKassa redirect payment
- YooKassa webhook
- идемпотентная обработка успешной оплаты
- health check
- Docker
- render.yaml

## ВАЖНО про бесплатный Render

Для магазина с реальными продажами не рассчитывайте на бесплатный Web Service как на постоянно работающий production-сервис. Выберите подходящий платный план Render.

## Шаг 1. MongoDB Atlas

Создайте MongoDB Atlas.

Рекомендуемая схема для Render + Atlas:
- Atlas Cloud Provider: AWS
- регион максимально близкий к региону Render.
- если Render в Frankfurt, используйте AWS eu-central-1 / Frankfurt.
MongoDB официально описывает эту интеграцию.

Создайте Database User с правами read/write на базу.

Network Access:
- для быстрого первого запуска можно временно разрешить 0.0.0.0/0;
- для production лучше использовать статические outbound IP Render, если они доступны вашему тарифу, и добавить их в Atlas IP Access List.

Получите connection string:
mongodb+srv://USER:PASSWORD@cluster.mongodb.net/?retryWrites=true&w=majority

## Шаг 2. GitHub

Создайте новый репозиторий.

Загрузите ВСЕ файлы этого проекта в корень репозитория:
Dockerfile
render.yaml
requirements.txt
app/
frontend/

НЕ загружайте .env.

## Шаг 3. Render

Render -> New -> Web Service -> подключите GitHub.

Если Render спрашивает runtime, выберите Docker.

Можно использовать Blueprint через render.yaml, либо создать Web Service вручную.

Service должен иметь публичный URL:
https://YOUR-SERVICE.onrender.com

Render сам завершает TLS/HTTPS перед вашим контейнером.

## Шаг 4. Environment Variables

В Render -> ваш Service -> Environment добавьте:

BOT_TOKEN
ADMIN_IDS
MONGODB_URI
MONGODB_DB=telegram_shop
PUBLIC_BASE_URL=https://YOUR-SERVICE.onrender.com
MINI_APP_URL=https://YOUR-SERVICE.onrender.com

YOOKASSA_SHOP_ID
YOOKASSA_SECRET_KEY
YOOKASSA_RETURN_URL=https://YOUR-SERVICE.onrender.com/

ADMIN_SECRET

Для первого запуска:
YOOKASSA_RECEIPT_ENABLED=false

## Шаг 5. Telegram Bot

В BotFather:
1. создайте бота;
2. получите BOT_TOKEN;
3. вставьте BOT_TOKEN в Render;
4. найдите свой Telegram ID и укажите его в ADMIN_IDS.

После успешного Deploy откройте бота и отправьте /start.

Приложение само установит Telegram webhook:
https://YOUR-SERVICE.onrender.com/telegram/webhook

## Шаг 6. Mini App

Кнопка /start уже открывает:
MINI_APP_URL

Поэтому после Deploy обязательно установите:
MINI_APP_URL=https://YOUR-SERVICE.onrender.com

Если URL изменился — обновите переменную и сделайте redeploy.

## Шаг 7. Админка

Откройте:
https://YOUR-SERVICE.onrender.com/static/admin.html

Введите значение ADMIN_SECRET.

Через админку можно:
- создавать товары;
- загружать фото;
- менять цену;
- менять остаток;
- скрывать товары;
- создавать доставки;
- создавать промокоды;
- смотреть заказы;
- менять статусы;
- смотреть обращения.

## Шаг 8. YooKassa

В кабинете YooKassa настройте магазин и получите Shop ID + Secret Key.

В webhook укажите:
https://YOUR-SERVICE.onrender.com/api/payments/yookassa

Событие:
payment.succeeded

## Шаг 9. 54-ФЗ / чеки

НЕ выставляйте значения налогов наугад.

Если ваш режим требует чек через YooKassa:
YOOKASSA_RECEIPT_ENABLED=true

И заполните:
YOOKASSA_TAX_SYSTEM_CODE=
YOOKASSA_VAT_CODE=

Значения должны соответствовать вашему налоговому режиму и товарам/услугам.

Также укажите email покупателя в заказе.

В проекте чек формируется по позициям заказа. Доставка передается отдельной позицией.

## Шаг 10. Проверка

После Deploy откройте:

https://YOUR-SERVICE.onrender.com/health

Должно быть:

{"ok":true}

Потом:
1. /start в Telegram;
2. открыть магазин;
3. увидеть пример товара;
4. открыть админку;
5. добавить реальный товар;
6. добавить фото;
7. добавить способ доставки;
8. проверить заказ;
9. проверить переход в YooKassa;
10. проверить webhook;
11. проверить изменение статуса;
12. проверить Telegram уведомление.

## Если Render показывает ошибки

Откройте:
Render -> Service -> Logs

Самые частые:
- MONGODB_URI неверный;
- MongoDB Network Access блокирует Render;
- BOT_TOKEN неверный;
- PUBLIC_BASE_URL не совпадает с реальным URL;
- MINI_APP_URL не совпадает с реальным URL;
- YooKassa credentials не заполнены.

## Хранение фотографий

Фотографии сохраняются в MongoDB GridFS. Это специально сделано для Render: локальный filesystem контейнера не используется как постоянное хранилище.

## Безопасность

Никогда не публикуйте:
- BOT_TOKEN
- YOOKASSA_SECRET_KEY
- MONGODB_URI с паролем
- ADMIN_SECRET

Храните их только в Render Environment Variables.

## Рекомендуемый порядок запуска

1. MongoDB Atlas
2. GitHub
3. Render
4. Environment Variables
5. Deploy
6. /health
7. /start
8. Admin
9. YooKassa
10. Тестовый платеж
11. Только после теста — реальные продажи
