# היועץ החכם להשקעות — גרסת Backend

הגרסה הזו מפרידה בין הממשק לבין מפתחות ה-API.

## מה השתנה
- מפתחות Alpaca ו-Alpha Vantage נשמרים רק בקובץ `.env` בצד השרת.
- הדפדפן מתחבר ל-WebSocket מקומי (`/ws/market/{SYMBOL}`).
- השרת מתחבר ל-Alpaca ומעביר לדפדפן Trades / Quotes / 1-minute bars.
- Alpha Vantage עובר דרך Proxy שרת מאובטח.
- נוסף endpoint בסיסי לסריקת Watchlist: `/api/scanner/watchlist`.
- נוסף endpoint Snapshot: `/api/live/snapshot/{symbol}`.

## התקנה

1. התקן Python 3.11 ומעלה.
2. פתח Terminal בתוך תיקיית הפרויקט.
3. צור סביבה וירטואלית (מומלץ).
4. התקן:

```bash
pip install -r requirements.txt
```

5. העתק:
```bash
cp .env.example .env
```

ב-Windows אפשר פשוט להעתיק את הקובץ ולשנות את שמו ל-`.env`.

6. הכנס ל-`.env` את המפתחות שלך:
```env
ALPHA_VANTAGE_API_KEY=...
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
ALPACA_FEED=iex
```

7. הפעל:
```bash
uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

8. פתח בדפדפן:
```text
http://127.0.0.1:8000
```

## Live
לחץ על מניה -> "הפעל Live".
אם Alpaca מוגדר, המחיר וה-bars יגיעו דרך WebSocket.

### IEX לעומת SIP
`iex` מתאים לניסוי ולשימוש חינמי, אך מייצג רק את IEX.
`SIP` הוא feed מאוחד של שוק המניות האמריקאי ודורש הרשאת נתונים מתאימה.

## אבטחה
אל תעלה את `.env` לענן/גיטהאב ואל תשלח אותו לאף אחד.
ה-Secret לא נשלח ל-JavaScript.

## סריקה
`/api/scanner/watchlist` הוא בסיס לסורק Live. סריקה מלאה של אלפי מניות דורשת:
- Universe מלא של סימולים פעילים.
- מגבלות API/Market-data plan מתאימות.
- חישוב Relative Volume, Gap, Float, News catalyst ו-Dilution בצד השרת.


## סורק שוק אוטומטי למסחר יומי

הגרסה החדשה כוללת `/api/scanner/day`.

הסורק:
1. מבקש מ-Alpaca את Top Market Movers ואת Most Active.
2. מאחד את המועמדות.
3. מושך Snapshot ו-20 ימי מחזור לכל מועמדת.
4. מחשב Relative Volume (RVOL), שינוי יומי, נזילות ומיקום בטווח היומי.
5. מושך חדשות Alpaca ומודד אם קיים קטליזטור טרי.
6. מחשב Day-Explosion Score ומחזיר Top 10.
7. ה-Frontend יכול לרענן אוטומטית כל דקה.

### Full Market Live
ה-screeners של Alpaca מבוססים על SIP. אם לחשבון אין הרשאה מתאימה, השרת מנסה Fallback דרך Alpha Vantage top gainers. אם גם זה לא זמין, הוא משתמש ב-watchlist רחב כדי שהממשק לא יישבר.

לכן:
- `ALPACA_FEED=sip` + הרשאת SIP מתאימה = מצב Full Market Live.
- `iex` = גרפים/מחירים Live מ-IEX, אבל סריקת Full Market דרך screeners עשויה לא להיות זמינה.


## Backtest היסטורי 6/12 חודשים

בלשונית **מעבדת השיטה** אפשר להריץ 6 חודשים או שנה.

המנוע פועל בשני שלבים כדי לצמצם look-ahead bias:
1. מוריד Daily bars ל-Universe רחב של מניות ארה"ב ומזהה ימי מועמדות לפי מידע שהיה ידוע בפתיחה (Gap, מחיר, מחזור היסטורי).
2. רק לאותם Symbol-Days מוריד 1-minute bars וחדשות, ומחשב ציון לפי מידע שהיה קיים עד 09:45 ET.

לצורך Recall, המנוע מוסיף גם ימים שבדיעבד עלו לפחות 15% מהפתיחה עד ה-high היומי, אך ה-outcome לא נכנס לחישוב הציון.

מדדים:
- Target 1 success: 1.5R לפני Stop.
- Target 2: 2.5R לפני Stop.
- False Positive.
- False Negative / Recall של "ימים מתפוצצים".
- Expectancy ב-R.
- תשואה ממוצעת וחציונית עד הסגירה.
- MFE / MAE.

### Caveat חשוב
רשימת assets של Alpaca כוללת גם statuses שונים כאשר לא מסננים ל-active בלבד, מה שמפחית survivorship bias, אבל אינה מבטיחה Universe point-in-time מושלם של כל מניה שנסחרה בכל יום היסטורי. לצורך מחקר מוסדי מדויק לחלוטין נדרש dataset point-in-time הכולל delistings/symbol history.


## למידת השיטה במסך הבית

לאחר הרצת Backtest, מסך הבית מציג אוטומטית:
- כמה סימולים היו ב-Universe.
- כמה מניות/אירועים נבדקו.
- כמה קיבלו אות קנייה לפי הסף.
- כמה מהאותות הגיעו ל-Target 1 ול-Target 2.
- אחוז הצלחה, Recall, False Positives ו-Expectancy.
- פילוח ביצועים לפי טווחי ציון: 70–79, 80–84, 85–89, 90–100.
- טבלת האותות האחרונים עם סימול, תאריך, Gap, RVOL והתוצאה בפועל.

הגדרת הצלחה ראשית: Target 1 (1.5R) הושג לפני ה-Stop. זהו מדד Backtest היסטורי ואינו מבטיח תוצאה עתידית.


## פרופיל אוטומטי של 5 שנים לכל מניה

בכל פתיחת מניה האפליקציה קוראת ל-`/api/history/5y/{symbol}` ומציגה:
- גרף יומי ל-5 שנים.
- תשואה מצטברת ו-CAGR.
- תנודתיות שנתית.
- Max Drawdown.
- שיא/שפל 5Y.
- MA50 / MA200 ומיקום המחיר ביחס ל-MA200.
- Gap ממוצע מוחלט.
- מספר ימי Gap של 10% ומעלה.
- מספר ימים שבהם ה-high היה לפחות 15% מעל ה-open.
- תשואה לכל שנה בנפרד.

### שימוש בלמידת השיטה
הפרופיל מאפשר לבדוק אם מניות בעלות "אופי" מסוים — למשל תנודתיות גבוהה, היסטוריית Gaps או ימי +15% — מייצרות תוצאות שונות בשיטת המסחר היומי.

חשוב: כדי למנוע look-ahead bias, פרופיל 5Y הנוכחי משמש כרקע למניה. בהרצת Backtest היסטורית אסור להשתמש במידע שהתרחש אחרי יום האות. לשילוב מלא של פיצ'רי 5Y בתוך ציון היסטורי נדרש לחשב אותם מחדש point-in-time לכל Symbol-Day.


## Rolling 5-Year Backtest

מנוע ה-Backtest מחשב כעת לכל Symbol-Day פרופיל היסטורי point-in-time שמסתיים יום לפני האות.

הפיצ'רים כוללים:
- תשואה היסטורית ו-CAGR.
- תנודתיות שנתית.
- Max Drawdown.
- Gap ממוצע ושיעור ימי Gap >=10%.
- שיעור ימים שבהם ה-high היה לפחות 15% מעל ה-open.
- מיקום מעל/מתחת MA200.

הפיצ'רים מקבלים התאמה קטנה ומוגבלת לציון. מסך הלמידה מציג לאחר ההרצה האם קבוצות אלה באמת הצליחו יותר או פחות:
- תנודתיות 35%-90%.
- היסטוריה גבוהה של ימי +15%.
- Gap profile 1.5%-4.5%.
- מעל MA200.
- תנודתיות קיצונית מעל 130%.
- Drawdown היסטורי עמוק מ-85%.

כך ניתן לבטל או לשנות משקל של פיצ'ר שאינו מוסיף Expectancy בפועל.


## UX refresh

הממשק הראשי צומצם לחמש לשוניות בלבד: ראשי, מסחר יומי, השקעות, התיק שלי והגדרות.
מידע היסטורי, שבוע אחרון ולמידת השיטה מוצגים בתוך עמוד המניה.

נוסף `/api/market/status` שמחזיר זמן שרת מסונכרן, שעון ישראל, שעון ניו-יורק וסטטוס מסחר.
כאשר Alpaca מוגדר, סטטוס פתיחת השוק והפתיחה/סגירה הבאה מגיעים מ-Alpaca Market Clock ו-Calendar.


## Data supervisor + strategy health

- מסך מניה משתמש ב-Alpaca תחילה, Alpha Vantage כגיבוי, ומקור מחיר ציבורי כגיבוי אחרון.
- כל Bundle מחזיר metadata של טריות הנתונים.
- חיבור WebSocket של Alpaca מתחדש אוטומטית במקרה של ניתוק, עם backoff.
- Watchdog מסמן חיבור חי שלא עדכן יותר מ-45 שניות.
- `/api/strategy/health` משווה את האותות האחרונים לתקופה הקודמת ומזהה הידרדרות ב-hit rate/Expectancy.
- מסך הבית מציג בריאות נתונים, Feed, גיל Backtest, hit rate אחרון, Expectancy ושיעור Stops.
- Backtest ישן משבוע מסומן ככזה שדורש רענון.

### הפעלה
ב-Windows יש להריץ `START_WINDOWS.bat`. אין לפתוח את `static/index.html` ישירות.
