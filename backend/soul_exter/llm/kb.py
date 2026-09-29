"""Built-in knowledge base for offline answers: trading & finance topics, countries, science / tech basics, small talk.

Everything here is a curated, checked statement — the offline responder never invents facts, it only retrieves them.
Matching is whole-word / whole-phrase, longest phrase wins."""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------------------------- trading & finance
# (keywords, answer). Keywords are matched as whole words/phrases (case-insensitive).
TOPICS: list[tuple[tuple[str, ...], str]] = [
    (("rsi", "relative strength index"), "RSI (Relative Strength Index) is a 0–100 momentum oscillator built from average gains vs average losses over N bars (usually 14). Above ~70 is often called overbought and below ~30 oversold, but in strong trends it can stay extreme for a long time, so it works best as a filter combined with trend and structure, not a stand-alone signal."),
    (("macd",), "MACD is the difference between a 12- and a 26-period exponential moving average, plotted with a 9-period signal line and a histogram. Crossovers of the MACD and signal lines hint at momentum shifts; divergences between MACD and price hint at weakening trends. It lags, so it confirms rather than predicts."),
    (("moving average", "sma", "ema", "moving averages"), "A moving average smooths price over N bars. The simple MA (SMA) weights all bars equally; the exponential MA (EMA) weights recent bars more, so it reacts faster. Traders use them for trend direction (price above a rising 50/200 MA is bullish), dynamic support/resistance, and crossovers such as the 50/200 'golden' and 'death' cross."),
    (("bollinger", "bollinger bands"), "Bollinger Bands are a moving average (usually 20) with bands at ±2 standard deviations. Bands narrow in quiet markets (a 'squeeze', often before a breakout) and widen in volatile ones. Price touching a band is not automatically a reversal signal — in a trend it often 'walks the band'."),
    (("atr", "average true range"), "ATR (Average True Range) measures how far an instrument typically moves per bar, including gaps. It is used to size stops (for example 1.5–2× ATR from entry) and position size so that each trade risks a comparable amount regardless of how volatile the asset is."),
    (("fibonacci retracement", "fib retracement", "fibonacci levels", "fib levels"), "Fibonacci retracements mark the 23.6 %, 38.2 %, 50 %, 61.8 % and 78.6 % pullback levels of a prior swing. Traders watch them as possible support/resistance in a pullback. They are self-fulfilling to a degree (many people watch them) and work best when they line up with other structure such as previous highs/lows or moving averages."),
    (("support and resistance", "support", "resistance"), "Support is a price zone where buying has repeatedly stopped a decline; resistance is where selling has repeatedly stopped a rise. Treat them as zones rather than exact lines. A broken resistance often becomes support later ('role reversal'), and the more times a level is tested, the more likely it eventually breaks."),
    (("trend line", "trendline", "trend following", "trend-following"), "Trend following means trading in the direction of the prevailing move (higher highs and higher lows = uptrend) and cutting losses quickly while letting winners run. It typically has a modest win rate (35–45 %) but large winners; it does badly in choppy sideways markets."),
    (("mean reversion", "mean-reversion"), "Mean reversion assumes prices that stretch far from their average tend to snap back. It usually has a high win rate with small gains and occasional large losses when a stretch turns into a real trend, so strict stops and position sizing are essential."),
    (("breakout", "breakouts"), "A breakout is a move through a well-defined level (range high/low, trend line, prior high). Confirmation such as rising volume, a close beyond the level, or a successful retest reduces the risk of a false breakout ('fakeout'). Place the stop back inside the range, where the breakout idea is proven wrong."),
    (("scalping", "scalper"), "Scalping targets many very small moves held for seconds to minutes. Edge is thin, so costs matter enormously: spreads, commissions and slippage can consume the whole advantage. It demands liquid instruments, fast execution and discipline."),
    (("day trading", "day trader", "intraday"), "Day trading opens and closes positions within the same session, avoiding overnight gap risk. It needs enough liquidity and volatility to overcome costs, strict daily loss limits, and a tested playbook; most retail day traders lose money, mainly through over-trading and oversized risk."),
    (("swing trading", "swing trade"), "Swing trading holds positions for days to weeks to capture a single 'swing' in a trend or range. It uses daily/4-hour charts, needs wider stops (so smaller position size), and is exposed to overnight gaps and news."),
    (("position trading",), "Position trading holds for weeks to months, driven by macro themes and the higher-timeframe trend. Fewer trades, wider stops, smaller size and patience are the hallmarks."),
    (("stop loss", "stop-loss", "stoploss"), "A stop loss is a pre-set order that closes a trade at a defined loss. Put it where your idea is proven wrong (beyond structure or a multiple of ATR), then size the position so that the distance to the stop equals your chosen risk, e.g. 0.5–1 % of the account. Never widen a stop after entry."),
    (("take profit", "take-profit", "profit target"), "A take-profit is a pre-set exit at a target price. Targets are usually set at a multiple of the risk (R) — for example 2R — or at the next structural level. Scaling out part of the position at 1R and trailing the rest is a common compromise."),
    (("risk reward", "risk-reward", "risk to reward", "reward to risk", "r:r", "rr ratio", "risk/reward"), "Risk-reward (R:R) compares the potential profit to the potential loss. With a 2:1 R:R you only need to win more than 33 % of trades to break even (before costs); at 1:1 you need over 50 %. Combine R:R with your realistic win rate: expectancy = win% × avg win − loss% × avg loss."),
    (("expectancy",), "Expectancy is the average result per trade: (win rate × average win) − (loss rate × average loss). Measured in R, an expectancy of +0.3R means that on average you make 0.3× your risk per trade. Positive expectancy over a large sample is the real test of a strategy."),
    (("position sizing", "position size", "size a position", "size my position", "size my trade", "lot size", "how many lots"), "Position size = (account × risk %) ÷ (stop distance × value per point). Example: 10,000 account, 1 % risk = 100; if the stop is 50 pips and one standard lot is worth 10 per pip, 100 ÷ (50 × 10) = 0.2 lots. Fixed-fraction sizing keeps any single loss small."),
    (("drawdown", "max drawdown"), "Drawdown is the fall from an equity peak to a later trough. A 50 % drawdown needs a 100 % gain to recover, which is why capping drawdown (daily loss limits, reducing size after losses) matters more than chasing returns."),
    (("sharpe", "sharpe ratio"), "The Sharpe ratio is the average excess return divided by the standard deviation of returns, annualised. Above ~1 is decent, above 2 is excellent — but it penalises upside volatility and can be flattered by short samples or hidden tail risk."),
    (("win rate", "winrate", "hit rate"), "Win rate is the share of trades that are profitable. It means little without payoff size: a 40 % win rate with 3R winners is very profitable; a 80 % win rate with tiny winners and large losers can lose money."),
    (("leverage",), "Leverage lets you control a large position with a small deposit (margin). It magnifies gains and losses equally: 30:1 leverage turns a 3.3 % adverse move into a 100 % loss of the margin. Use it to be capital-efficient, not to size up beyond your per-trade risk limit."),
    (("margin call", "margin", "stop out", "stop-out"), "Margin is the deposit that keeps a leveraged position open. If losses reduce your equity so that the margin level falls below the broker's threshold you get a margin call, and below the stop-out level the broker starts closing positions automatically."),
    (("pip", "pips", "pipette"), "A pip is the standard smallest quoted price step in FX — 0.0001 for most pairs (0.01 for JPY pairs). A pipette is a tenth of a pip. For a standard lot (100,000 units) one pip of EURUSD is worth about 10 USD."),
    (("spread", "bid ask", "bid-ask", "bid/ask"), "The spread is the difference between the best ask (buy) and best bid (sell) price. It is the basic cost of trading: you pay it on entry and, effectively, on exit. It widens at illiquid times (rollover, holidays) and around news."),
    (("slippage",), "Slippage is the difference between the price you expected and the price you got. It grows with volatility, order size and thin liquidity, and it affects market and stop orders most. Limit orders avoid slippage but may not fill."),
    (("market order", "limit order", "stop order", "order types", "stop limit", "pending order"), "A market order fills immediately at the best available price. A limit order fills only at your price or better (buy below / sell above the market). A stop order becomes a market order once price reaches a trigger (used for stop losses and breakout entries). A stop-limit is a stop that turns into a limit order instead."),
    (("forex", "fx market", "foreign exchange"), "Forex is the decentralised market for exchanging currencies, trading about 7 trillion USD a day, 24 hours a day from Monday to Friday. It is quoted in pairs (EURUSD = how many USD per 1 EUR) and driven by interest-rate differentials, growth, risk sentiment and central-bank policy."),
    (("currency pair", "major pairs", "cross pairs", "exotic pairs"), "Major pairs all include USD (EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD, NZDUSD) and have the tightest spreads. Crosses have no USD (EURGBP, EURJPY, GBPJPY). Exotics pair a major with an emerging-market currency (USDTRY, USDZAR, USDMXN) — wider spreads and higher gap risk."),
    (("trading session", "trading sessions", "london session", "new york session", "tokyo session", "asian session", "best time to trade"), "FX has four overlapping sessions: Sydney, Tokyo (Asia), London and New York. Liquidity and volatility peak when London and New York overlap (about 13:00–17:00 UTC), and EUR/GBP pairs move most in the London session. Asia tends to be quieter and range-bound, except for JPY and AUD crosses."),
    (("interest rate", "central bank", "fed", "federal reserve", "ecb", "rate hike", "rate cut"), "Central banks steer the economy mainly through interest rates. Higher rates tend to strengthen a currency (higher yield) and weigh on stocks and gold; cuts do the reverse. Markets move most on the surprise relative to expectations, not on the decision itself."),
    (("nfp", "non farm payrolls", "nonfarm payrolls"), "Non-Farm Payrolls is the US monthly jobs report, released on the first Friday of the month at 13:30 UTC. It is one of the most volatile events for USD pairs, gold and indices; spreads widen and slippage rises, so many traders stand aside or reduce size around the release."),
    (("cpi", "consumer price index"), "CPI measures the average change in consumer prices and is the headline inflation gauge. Hotter-than-expected CPI raises the odds of rate hikes (usually USD-positive, stocks/gold-negative); cooler CPI does the opposite."),
    (("gdp", "gross domestic product"), "GDP is the total value of goods and services an economy produces in a period. Stronger-than-expected growth typically supports the currency and equities; contraction for two straight quarters is the common definition of a recession."),
    (("inflation",), "Inflation is a broad rise in prices, eroding what each unit of currency buys. Central banks target roughly 2 %. Traders watch CPI, PCE and wage data because inflation drives rate expectations, which drive currencies, bonds and stocks."),
    (("recession",), "A recession is a significant, broad decline in economic activity, often defined as two consecutive quarters of falling GDP. Risk assets usually fall ahead of it, safe havens (USD, JPY, CHF, government bonds, gold) tend to rise, and central banks typically cut rates."),
    (("gold", "xauusd"), "Gold (XAUUSD) is a classic safe haven and inflation hedge. It usually moves inversely to real interest rates and the US dollar and rises in times of geopolitical stress. It is volatile intraday, so use wider stops and smaller size than for major FX pairs."),
    (("oil", "crude oil", "wti", "brent"), "Crude oil (WTI in the US, Brent globally) is driven by supply (OPEC+, shale output, inventories), demand (global growth) and geopolitics. It has large gaps around OPEC decisions and weekly inventory reports (Wednesdays)."),
    (("crypto", "cryptocurrency", "bitcoin", "btc", "ethereum", "eth"), "Cryptocurrencies trade 24/7 and are far more volatile than FX or stocks: daily moves of 5–10 % are normal for altcoins. Bitcoin acts partly as a macro/liquidity asset, and altcoins tend to follow it with higher beta. Because of the volatility, use smaller position sizes and wider stops."),
    (("stock", "stocks", "equity", "equities", "shares"), "A stock is an ownership share in a company. Prices reflect expected future earnings and are influenced by earnings reports, sector trends, interest rates and market sentiment. Indices such as the S&P 500 bundle many stocks and are less risky than single names."),
    (("index", "indices", "s&p 500", "sp500", "nasdaq", "dow jones", "dax", "ftse"), "A stock index tracks a basket of stocks: the S&P 500 (500 large US companies), Nasdaq 100 (large tech-heavy US companies), Dow Jones (30 US blue chips), DAX (40 German companies), FTSE 100 (UK). Index CFDs and futures let you trade the whole market with one instrument."),
    (("futures", "future contract"), "A futures contract is a standardised agreement to buy or sell an asset at a set price on a future date. They are traded on exchanges with daily margin settlement and are used both to hedge and to speculate on indices, commodities, currencies and rates."),
    (("options", "call option", "put option", "option contract"), "An option gives the buyer the right (not the obligation) to buy (call) or sell (put) an asset at a strike price before expiry. The buyer's maximum loss is the premium paid; the seller takes the opposite risk. Prices depend on the underlying price, strike, time to expiry, volatility and interest rates (the 'Greeks')."),
    (("delta", "gamma", "theta", "vega", "the greeks", "greeks"), "The option Greeks measure sensitivity: delta = change in option price per 1 move in the underlying, gamma = change in delta, theta = time decay per day, vega = sensitivity to implied volatility. Long options have positive gamma/vega and negative theta; short options the reverse."),
    (("implied volatility", "iv", "vix"), "Implied volatility is the market's forecast of future price variability, backed out of option prices. The VIX is the implied volatility of S&P 500 options over 30 days — the 'fear gauge': it usually spikes when stocks fall."),
    (("cfd", "contract for difference"), "A CFD is a derivative that lets you speculate on price moves without owning the asset; you pay the spread, possibly overnight financing, and trade with leverage. Most retail CFD accounts lose money, so use strict risk management."),
    (("hedge", "hedging"), "Hedging means opening an offsetting position to reduce risk — for example shorting an index against a stock portfolio, or buying a put option as insurance. It lowers risk (and usually expected return) rather than removing it."),
    (("diversification", "diversify"), "Diversification spreads risk across assets that do not move together. It only helps if the correlation is low: in a crisis correlations often jump towards 1, so also limit total open risk and avoid several trades that are really the same bet."),
    (("correlation",), "Correlation measures how two assets move together, from −1 (opposite) to +1 (in lockstep). EURUSD and GBPUSD are usually strongly positively correlated, so long both is close to doubling one position. Correlation changes over time and is estimated from returns, not prices."),
    (("candlestick", "candlesticks", "candle"), "A candlestick shows open, high, low and close for a period: the body spans open to close (green/white if up, red/black if down) and the wicks show the extremes. Long wicks show rejection of a price level; long bodies show conviction."),
    (("doji",), "A doji is a candle whose open and close are nearly equal, forming a cross. It signals indecision; it matters most after a strong trend or at a key level, and needs confirmation from the next candle."),
    (("hammer", "shooting star", "pin bar"), "A hammer (long lower wick after a decline) and a shooting star (long upper wick after a rally) are single-candle reversal patterns: price was pushed far and rejected. They gain weight at support/resistance and when the following candle confirms."),
    (("engulfing",), "An engulfing pattern is a two-candle reversal: the second candle's body fully covers the previous body in the opposite direction. A bullish engulfing after a decline (or bearish after a rally) hints that control has flipped, especially at a key level."),
    (("head and shoulders", "head & shoulders"), "Head and shoulders is a reversal pattern: three peaks with the middle (head) highest, and a 'neckline' under the troughs. A close below the neckline signals a potential trend change; the measured target is the head-to-neckline distance projected down."),
    (("double top", "double bottom"), "A double top (two failed attempts at a high) and double bottom (two holds at a low) are reversal patterns; they are confirmed when price breaks the middle trough/peak. Volume typically falls on the second attempt."),
    (("triangle", "flag", "pennant", "wedge", "chart pattern", "chart patterns"), "Continuation patterns such as flags, pennants and triangles show consolidation inside a trend; the usual expectation is a breakout in the direction of the prior move. Wedges lean against the trend and often precede reversals. All patterns need a defined invalidation level and confirmation."),
    (("volume",), "Volume is the number of units traded in a period. Moves on rising volume are more trustworthy than moves on falling volume; a breakout without volume is suspect. In spot FX there is no central volume, so tick volume is used as a proxy."),
    (("vwap",), "VWAP (volume-weighted average price) is the average price weighted by volume for the session so far. Institutions use it as a benchmark; intraday traders treat price above VWAP as bullish bias and below as bearish, and use it as dynamic support/resistance."),
    (("order flow", "order book", "market depth", "level 2", "dom"), "Order flow analysis studies the actual buying and selling: the order book (resting limit orders), executed trades and their imbalance. Persistent buy-side imbalance (positive order-flow imbalance) tends to precede short-term upward pressure, but it can be spoofed and decays within seconds to minutes."),
    (("liquidity",), "Liquidity is how easily an asset can be traded without moving its price: tight spreads, deep order books and high volume. Liquidity dries up around holidays, rollovers and shocks, which is when slippage and gaps happen."),
    (("volatility",), "Volatility is how much and how fast prices move, usually measured as the standard deviation of returns or ATR. It clusters (quiet periods follow quiet periods and vice versa), which is why position size should shrink when volatility is high."),
    (("technical analysis",), "Technical analysis studies price and volume history — trends, levels, patterns and indicators — to judge probabilities of future moves. It assumes prices reflect all information and that behaviour repeats; it works best as a framework for entries, stops and risk, not as a crystal ball."),
    (("fundamental analysis",), "Fundamental analysis values an asset from economic and company data: growth, inflation, interest rates, earnings, balance sheets. In FX it focuses on rate differentials, growth and trade balances; in stocks on earnings, margins and valuation."),
    (("sentiment", "risk on", "risk-on", "risk off", "risk-off"), "Risk-on means investors favour growth assets (stocks, AUD, NZD, crypto); risk-off means they flee to safety (USD, JPY, CHF, gold, government bonds). Sentiment shifts drive strong correlated moves across markets."),
    (("dollar index", "dxy"), "The US Dollar Index (DXY) measures the dollar against a basket of six currencies (EUR ≈ 58 %, JPY, GBP, CAD, SEK, CHF). It is used as a gauge of broad USD strength and often moves inversely to gold, EURUSD and risk assets."),
    (("carry trade",), "A carry trade borrows in a low-interest currency (historically JPY, CHF) and invests in a high-yield one, earning the interest difference (swap). It works in calm, risk-on markets and unwinds violently in risk-off shocks."),
    (("swap", "rollover", "overnight financing"), "A swap (rollover) is the interest paid or earned for holding a leveraged position overnight, based on the interest-rate difference between the two currencies (plus broker markup). Wednesday rollover is usually charged triple because of T+2 settlement."),
    (("demo account", "paper trading", "paper trade"), "A demo or paper account trades with virtual money at real prices. It is ideal for testing a strategy and platform mechanics, but it cannot reproduce the emotions, slippage and partial fills of live trading, so move to small live size gradually."),
    (("backtest", "backtesting"), "Backtesting applies rules to historical data to estimate how a strategy would have performed. Guard against overfitting (too many tuned parameters), look-ahead bias, ignoring costs, and small samples; validate on out-of-sample data and with walk-forward tests before risking money."),
    (("overfitting", "curve fitting"), "Overfitting means a strategy is tuned so tightly to past data that it captures noise instead of a real edge, so it fails on new data. Fewer parameters, out-of-sample tests, and a plausible economic reason for the edge are the main defences."),
    (("trading psychology", "fomo", "revenge trading", "overtrading", "discipline"), "Most trading losses come from behaviour, not analysis: FOMO (chasing a move), revenge trading (trying to win back a loss), over-trading, moving stops, and oversizing after wins. Fixed risk per trade, a written plan, a daily loss limit and a trading journal are the practical antidotes."),
    (("trading journal", "journal"), "A trading journal records every trade: setup, reasons, entry/stop/target, result in R, screenshots and how you felt. Reviewing it weekly exposes which setups actually pay and which mistakes repeat."),
    (("kelly", "kelly criterion"), "The Kelly criterion gives the bet size that maximises long-run growth: f = W − (1 − W)/R, where W is the win probability and R the win/loss ratio. Full Kelly is very aggressive and sensitive to estimation error, so practitioners use a fraction (half or quarter Kelly)."),
    (("martingale",), "Martingale doubles the position after each loss to recover everything with one win. It looks profitable until a long losing streak or margin limit wipes out the account — the risk of ruin is hidden but large, so serious risk management avoids it."),
    (("hedge fund", "prop firm", "proprietary trading"), "A prop (proprietary trading) firm gives traders its capital, often after passing an evaluation with strict rules (profit target, daily and maximum drawdown limits), in exchange for a share of the profits. A hedge fund pools investor money and runs strategies with fees on assets and performance."),
    (("broker", "brokers", "ecn", "market maker"), "A broker gives you access to the market. A market maker takes the other side of your trade and quotes its own prices; an ECN/STP broker routes orders to liquidity providers and charges commission plus a raw spread. Check regulation (FCA, ASIC, CySEC, SEC/CFTC), execution quality and withdrawal record."),
    (("metatrader", "mt5", "mt4", "metatrader 5"), "MetaTrader 4/5 are popular retail trading platforms from MetaQuotes with charts, indicators, Expert Advisors (automated strategies) and a Python API for MT5 (Windows only). A demo account on the MetaQuotes-Demo server is free for testing."),
    (("expert advisor", "trading bot", "algo trading", "algorithmic trading", "algo"), "Algorithmic trading executes rules automatically. Its advantages are speed, discipline and testability; its risks are overfitting, bugs, connectivity failures and regime change. Start with tiny size, add kill-switches (max daily loss, max open trades) and monitor it."),
    (("tax", "trading tax"), "Tax on trading depends on your country and status (investor vs trader, capital gains vs income, holding period, derivatives rules). Keep complete records and ask a local tax professional — I can't give tax advice for your jurisdiction."),
    (("bull market", "bear market", "bullish", "bearish"), "A bull market is a sustained rise (commonly 20 %+ from a low), a bear market a sustained decline of 20 %+ from a high. 'Bullish' means expecting prices to rise, 'bearish' expecting them to fall."),
    (("gap", "gaps"), "A gap is a jump between one bar's close and the next bar's open with no trades in between, usually caused by news over a weekend or overnight. Stops do not protect against gaps — they fill at the next available price, which is why weekend risk needs smaller size."),
    (("pivot points", "pivot point"), "Pivot points are support/resistance levels computed from the prior period's high, low and close: P = (H + L + C)/3, with R1 = 2P − L and S1 = 2P − H, and further levels. Intraday traders use them as reference levels and as a bias filter (above P = bullish)."),
    (("stochastic", "stochastic oscillator"), "The stochastic oscillator compares the close to the recent high-low range on a 0–100 scale (overbought > 80, oversold < 20). Like RSI it is a momentum tool that works best in ranges and needs trend confirmation in trending markets."),
    (("adx", "average directional index"), "ADX measures trend strength (not direction) from 0–100: below ~20 suggests a range, above ~25 a trending market, above ~40 a very strong trend. Use it to choose between trend-following and mean-reversion tactics."),
    (("ichimoku",), "Ichimoku Cloud combines five lines (Tenkan, Kijun, Senkou A/B, Chikou) to show trend, momentum and support/resistance at a glance. Price above the cloud is bullish, below is bearish, and the cloud's thickness shows the strength of the level."),
    (("elliott wave",), "Elliott Wave theory proposes that markets move in five-wave impulses with three-wave corrections. It is highly subjective (different analysts count differently), so treat it as a scenario framework with strict invalidation levels."),
    (("fly brain", "drosophila", "mushroom body", "kenyon cell"), "The fly-brain hunter on this floor is inspired by the Drosophila olfactory system: 29 market 'senses' feed 26 projection neurons, which are expanded into 140 sparse Kenyon cells and read out by 8 mushroom-body output neurons (attack, wait, retreat, investigate, hold, hedge, scale, abort). Realised trade results feed back as dopamine that reshapes the Kenyon-to-output weights."),
]

# ---------------------------------------------------------------------------------------------- geography
# country -> (capital, currency, continent)
COUNTRIES: dict[str, tuple[str, str, str]] = {
    "india": ("New Delhi", "Indian rupee (INR)", "Asia"), "china": ("Beijing", "renminbi/yuan (CNY)", "Asia"),
    "japan": ("Tokyo", "yen (JPY)", "Asia"), "south korea": ("Seoul", "won (KRW)", "Asia"), "pakistan": ("Islamabad", "Pakistani rupee (PKR)", "Asia"),
    "bangladesh": ("Dhaka", "taka (BDT)", "Asia"), "sri lanka": ("Sri Jayawardenepura Kotte (Colombo is the commercial capital)", "Sri Lankan rupee (LKR)", "Asia"),
    "nepal": ("Kathmandu", "Nepalese rupee (NPR)", "Asia"), "indonesia": ("Jakarta", "rupiah (IDR)", "Asia"), "thailand": ("Bangkok", "baht (THB)", "Asia"),
    "vietnam": ("Hanoi", "dong (VND)", "Asia"), "malaysia": ("Kuala Lumpur", "ringgit (MYR)", "Asia"), "singapore": ("Singapore", "Singapore dollar (SGD)", "Asia"),
    "philippines": ("Manila", "Philippine peso (PHP)", "Asia"), "saudi arabia": ("Riyadh", "riyal (SAR)", "Asia"), "uae": ("Abu Dhabi", "dirham (AED)", "Asia"),
    "united arab emirates": ("Abu Dhabi", "dirham (AED)", "Asia"), "qatar": ("Doha", "riyal (QAR)", "Asia"), "turkey": ("Ankara", "lira (TRY)", "Asia/Europe"),
    "israel": ("Jerusalem (Tel Aviv hosts most embassies)", "shekel (ILS)", "Asia"), "iran": ("Tehran", "rial (IRR)", "Asia"), "iraq": ("Baghdad", "dinar (IQD)", "Asia"),
    "afghanistan": ("Kabul", "afghani (AFN)", "Asia"), "kazakhstan": ("Astana", "tenge (KZT)", "Asia"), "hong kong": ("Hong Kong", "Hong Kong dollar (HKD)", "Asia"),
    "united kingdom": ("London", "pound sterling (GBP)", "Europe"), "uk": ("London", "pound sterling (GBP)", "Europe"), "england": ("London", "pound sterling (GBP)", "Europe"),
    "france": ("Paris", "euro (EUR)", "Europe"), "germany": ("Berlin", "euro (EUR)", "Europe"), "italy": ("Rome", "euro (EUR)", "Europe"), "spain": ("Madrid", "euro (EUR)", "Europe"),
    "portugal": ("Lisbon", "euro (EUR)", "Europe"), "netherlands": ("Amsterdam", "euro (EUR)", "Europe"), "belgium": ("Brussels", "euro (EUR)", "Europe"),
    "switzerland": ("Bern", "Swiss franc (CHF)", "Europe"), "austria": ("Vienna", "euro (EUR)", "Europe"), "sweden": ("Stockholm", "krona (SEK)", "Europe"),
    "norway": ("Oslo", "krone (NOK)", "Europe"), "denmark": ("Copenhagen", "krone (DKK)", "Europe"), "finland": ("Helsinki", "euro (EUR)", "Europe"),
    "ireland": ("Dublin", "euro (EUR)", "Europe"), "poland": ("Warsaw", "zloty (PLN)", "Europe"), "greece": ("Athens", "euro (EUR)", "Europe"),
    "russia": ("Moscow", "ruble (RUB)", "Europe/Asia"), "ukraine": ("Kyiv", "hryvnia (UAH)", "Europe"), "czech republic": ("Prague", "koruna (CZK)", "Europe"),
    "hungary": ("Budapest", "forint (HUF)", "Europe"), "romania": ("Bucharest", "leu (RON)", "Europe"),
    "united states": ("Washington, D.C.", "US dollar (USD)", "North America"), "usa": ("Washington, D.C.", "US dollar (USD)", "North America"),
    "america": ("Washington, D.C.", "US dollar (USD)", "North America"), "canada": ("Ottawa", "Canadian dollar (CAD)", "North America"),
    "mexico": ("Mexico City", "peso (MXN)", "North America"), "brazil": ("Brasília", "real (BRL)", "South America"), "argentina": ("Buenos Aires", "peso (ARS)", "South America"),
    "chile": ("Santiago", "peso (CLP)", "South America"), "colombia": ("Bogotá", "peso (COP)", "South America"), "peru": ("Lima", "sol (PEN)", "South America"),
    "australia": ("Canberra", "Australian dollar (AUD)", "Oceania"), "new zealand": ("Wellington", "New Zealand dollar (NZD)", "Oceania"),
    "south africa": ("Pretoria (executive), Cape Town (legislative), Bloemfontein (judicial)", "rand (ZAR)", "Africa"), "egypt": ("Cairo", "Egyptian pound (EGP)", "Africa"),
    "nigeria": ("Abuja", "naira (NGN)", "Africa"), "kenya": ("Nairobi", "shilling (KES)", "Africa"), "ethiopia": ("Addis Ababa", "birr (ETB)", "Africa"),
    "ghana": ("Accra", "cedi (GHS)", "Africa"), "morocco": ("Rabat", "dirham (MAD)", "Africa"),
}

# ---------------------------------------------------------------------------------------------- science, tech, everyday
GENERAL: list[tuple[tuple[str, ...], str]] = [
    (("speed of light",), "The speed of light in vacuum is 299,792,458 m/s (about 300,000 km/s)."),
    (("boiling point of water",), "Water boils at 100 °C (212 °F) at standard sea-level pressure; it is lower at altitude."),
    (("how many planets", "planets in the solar system"), "There are eight planets: Mercury, Venus, Earth, Mars, Jupiter, Saturn, Uranus and Neptune."),
    (("largest planet",), "Jupiter is the largest planet in the Solar System — over 11 times Earth's diameter."),
    (("tallest mountain", "highest mountain", "mount everest"), "Mount Everest, on the Nepal–China border, is the highest mountain above sea level at about 8,849 m."),
    (("longest river",), "The Nile and the Amazon are usually cited as the longest rivers, at roughly 6,650 km and 6,400 km depending on how they are measured."),
    (("largest ocean", "biggest ocean"), "The Pacific Ocean is the largest, covering about a third of Earth's surface."),
    (("world population", "population of the world", "how many people live on earth"), "The world's population is a little over 8 billion people (passed 8 billion in late 2022)."),
    (("what is ai", "artificial intelligence"), "Artificial intelligence is the field of building systems that perform tasks that normally need human intelligence — perception, language, planning and learning. Modern AI is mostly machine learning: models trained on large data sets."),
    (("machine learning",), "Machine learning is a set of methods in which programs learn patterns from data instead of being explicitly programmed — supervised (labelled examples), unsupervised (structure discovery) and reinforcement learning (trial, error and reward)."),
    (("neural network", "neural networks"), "An artificial neural network is a layered function made of simple units (neurons) with adjustable weights, trained by gradient descent to reduce a loss. Deep networks with many layers power modern vision, speech and language models."),
    (("chatgpt", "gpt", "large language model", "llm"), "A large language model (LLM) such as GPT is a neural network trained on huge amounts of text to predict the next token; that ability lets it answer questions, write and summarise. It can be wrong or make things up, so important facts should be checked."),
    (("python",), "Python is a readable, general-purpose programming language popular in data science, automation, web back-ends and AI. This floor's back-end is written in Python with FastAPI."),
    (("javascript", "typescript"), "JavaScript is the programming language of the web browser; TypeScript is JavaScript with static types that compile to plain JavaScript. This floor's 3D front-end uses TypeScript, React and three.js."),
    (("react",), "React is a JavaScript library for building user interfaces from components that re-render when their state changes."),
    (("three.js", "threejs", "webgl"), "three.js is a JavaScript library that makes WebGL 3D graphics easier: scenes, cameras, lights, meshes and materials. The trading hall is rendered with it."),
    (("fastapi",), "FastAPI is a modern Python web framework for building APIs with type hints, automatic validation and interactive docs; it runs on ASGI servers such as uvicorn."),
    (("git", "github"), "Git is a distributed version-control system that records snapshots of your files; GitHub hosts Git repositories and adds pull requests, issues and CI."),
    (("docker",), "Docker packages an application with its dependencies into a container that runs the same way everywhere, using OS-level virtualisation rather than a full virtual machine."),
    (("blockchain",), "A blockchain is an append-only ledger in which blocks of records are chained by cryptographic hashes and agreed by a distributed network, making past entries very hard to alter."),
    (("photosynthesis",), "Photosynthesis is how plants, algae and some bacteria turn light, water and carbon dioxide into sugar and oxygen."),
    (("gravity",), "Gravity is the attraction between masses. On Earth it accelerates falling objects at about 9.8 m/s²; in general relativity it is the curvature of spacetime."),
    (("dna",), "DNA (deoxyribonucleic acid) is the molecule that stores genetic information as a sequence of four bases (A, T, C, G) in a double helix."),
    (("water cycle",), "The water cycle moves water between oceans, air and land: evaporation and transpiration lift it into the atmosphere, condensation forms clouds, precipitation returns it, and runoff and groundwater carry it back to the sea."),
    (("climate change", "global warming"), "Climate change is the long-term rise in Earth's average temperature and shift in weather patterns, mainly driven since the 1800s by greenhouse gases from burning fossil fuels, which trap heat in the atmosphere."),
    (("healthy sleep", "how much sleep"), "Most adults do best with about 7–9 hours of sleep a night, at consistent times. This is general information, not medical advice."),
    (("pythagorean theorem", "pythagoras"), "In a right triangle the square of the hypotenuse equals the sum of the squares of the other two sides: a² + b² = c²."),
    (("area of a circle",), "The area of a circle is π × r² (r = radius); its circumference is 2 × π × r."),
    (("prime number", "prime numbers"), "A prime number is a whole number greater than 1 whose only divisors are 1 and itself: 2, 3, 5, 7, 11, 13…"),
    (("fibonacci sequence", "fibonacci numbers"), "The Fibonacci sequence starts 0, 1 and each next number is the sum of the previous two: 0, 1, 1, 2, 3, 5, 8, 13, 21…"),
    (("democracy",), "Democracy is a system of government in which power rests with the people, exercised directly or through elected representatives."),
    (("who invented the telephone", "inventor of the telephone"), "Alexander Graham Bell is credited with patenting the first practical telephone in 1876."),
    (("who wrote romeo and juliet", "romeo and juliet"), "Romeo and Juliet was written by William Shakespeare, around 1595."),
    (("year did world war 2 end", "when did world war 2 end", "when did world war ii end"), "World War II ended in 1945 — in Europe on 8 May (V-E Day) and in Asia on 2 September after Japan's surrender."),
    (("who wrote hamlet", "author of hamlet"), "Hamlet was written by William Shakespeare, around 1600."),
    (("who wrote pride and prejudice",), "Pride and Prejudice (1813) was written by Jane Austen."),
    (("who wrote 1984", "author of 1984"), "1984 was written by George Orwell and published in 1949."),
    (("who painted the mona lisa", "mona lisa"), "The Mona Lisa was painted by Leonardo da Vinci in the early 1500s."),
    (("who discovered gravity", "who discovered penicillin", "who discovered america"), "Isaac Newton formulated the law of universal gravitation (1687); Alexander Fleming discovered penicillin (1928); Europeans reached the Americas in 1492 under Christopher Columbus, though the continents were already inhabited for thousands of years. Tell me which one you meant if you need detail."),
    (("who developed the theory of relativity", "theory of relativity", "e=mc2", "e = mc2"), "Albert Einstein published special relativity in 1905 and general relativity in 1915. E = mc² says energy equals mass times the speed of light squared."),
    (("who invented the light bulb", "who invented the lightbulb"), "Thomas Edison made the first commercially practical incandescent bulb (1879); Joseph Swan developed one at the same time in Britain."),
    (("who invented the internet", "who invented the world wide web"), "The internet grew out of ARPANET and the TCP/IP protocols (Vint Cerf and Bob Kahn, 1970s); the World Wide Web was invented by Tim Berners-Lee in 1989–1991."),
    (("first man on the moon", "first person on the moon", "first human on the moon"), "Neil Armstrong was first on the Moon, on 20 July 1969 during Apollo 11, followed by Buzz Aldrin."),
    (("first president of the united states", "first us president"), "George Washington was the first President of the United States (1789–1797)."),
    (("who is the father of the nation india", "father of the nation"), "Mahatma Gandhi is called the Father of the Nation in India."),
    (("largest country", "biggest country"), "Russia is the largest country by area (about 17.1 million km²); the largest by population is India (about 1.4 billion), just ahead of China."),
    (("smallest country",), "Vatican City is the smallest country by area, about 0.44 km²."),
    (("hottest planet",), "Venus is the hottest planet (about 465 °C at the surface), thanks to a dense carbon-dioxide atmosphere."),
    (("closest star", "nearest star"), "Apart from the Sun, the nearest star is Proxima Centauri, about 4.24 light-years away."),
    (("chemical symbol for gold", "symbol for gold"), "The chemical symbol for gold is Au (from the Latin aurum)."),
    (("chemical formula of water", "formula of water", "h2o"), "Water is H₂O — two hydrogen atoms bonded to one oxygen atom."),
    (("how many continents",), "There are seven continents: Asia, Africa, North America, South America, Antarctica, Europe and Australia/Oceania."),
    (("how many days in a year", "days in a leap year"), "A normal year has 365 days; a leap year has 366 (every 4 years, except century years not divisible by 400)."),
    (("how many bones", "bones in the human body"), "An adult human body has 206 bones."),
    (("what is the internet",), "The internet is the global network of networks that connects computers using the TCP/IP protocols; the web, email and streaming are services that run on top of it."),
    (("what is an api", "what is api"), "An API (application programming interface) is a defined way for one program to ask another for data or actions, usually over HTTP with JSON — this floor's front-end talks to its back-end through one."),
    (("what is cloud computing", "cloud computing"), "Cloud computing rents computing power, storage and services over the internet on demand instead of owning the hardware."),
    (("what is a database", "sql"), "A database stores structured data so it can be queried efficiently. SQL (Structured Query Language) is the standard language for relational databases such as PostgreSQL and MySQL."),
    (("what is cryptography", "encryption"), "Encryption scrambles data with a key so only the holder of the right key can read it — symmetric (one shared key, e.g. AES) or asymmetric (public/private key pair, e.g. RSA)."),
    (("what is vitamin c", "vitamin c"), "Vitamin C (ascorbic acid) supports the immune system and collagen formation; it is found in citrus fruits, peppers and berries. This is general information, not medical advice."),
    (("hello world",), "\"Hello, World!\" is the traditional first program: print those words to confirm your setup works. In Python: print(\"Hello, World!\")."),
    (("how to learn trading", "learn to trade", "start trading", "beginner trader", "how to start trading"), "A sensible path: (1) learn the basics — order types, leverage, position sizing and costs; (2) pick one market and one simple, testable strategy; (3) paper-trade it for a few hundred trades while keeping a journal; (4) go live with tiny size, risking 0.25–1 % per trade; (5) review results weekly. Most beginners fail from oversizing and over-trading, not from bad indicators."),
    (("how to become rich", "get rich", "make money fast"), "There is no reliable shortcut. Durable wealth usually comes from earning more, spending less than you earn, investing regularly in diversified assets for a long time, and avoiding large, leveraged bets. Anything promising fast, guaranteed returns is a red flag."),
]

JOKES = [
    "Why did the trader bring a ladder to the desk? Because the market was going up and he wanted to get in on the ground floor of the next level.",
    "I told my stop-loss a joke. It didn't laugh — it just cut the conversation short.",
    "A bull, a bear and a fly walk into a trading hall. The fly says, \"I sense a setup.\" The other two say, \"We sense a spread.\"",
    "My risk manager and I have a great relationship: he says no, and I learn to respect it.",
]

# ---------------------------------------------------------------------------------------------- lookup
_cache: dict[str, re.Pattern] = {}


def _rx(k: str) -> re.Pattern:
    p = _cache.get(k)
    if p is None:
        p = _cache[k] = re.compile(r"(?<![A-Za-z0-9])" + re.escape(k) + r"(?![A-Za-z0-9])", re.I)
    return p


def _best(q: str, table: list[tuple[tuple[str, ...], str]]) -> tuple[int, str] | None:
    best: tuple[int, str] | None = None
    for keys, ans in table:
        for k in keys:
            if _rx(k).search(q):
                sc = len(k)
                if best is None or sc > best[0]:
                    best = (sc, ans)
    return best


def topic(q: str) -> str | None:
    """best trading/finance or general-knowledge entry for the question (longest matching phrase wins)"""
    a, b = _best(q, TOPICS), _best(q, GENERAL)
    c = a if (a and (not b or a[0] >= b[0])) else b
    return c[1] if c else None


def country(q: str) -> str | None:
    s = q.lower()
    names = sorted(COUNTRIES, key=len, reverse=True)
    for n in names:
        if not _rx(n).search(s):
            continue
        cap, cur, cont = COUNTRIES[n]
        nice = n.upper() if len(n) <= 3 else n.title()
        if re.search(r"\bcapital\b", s):
            return f"The capital of {nice} is {cap}."
        if re.search(r"\b(currency|money|coin)\b", s):
            return f"The currency of {nice} is the {cur}."
        if re.search(r"\bcontinent\b", s):
            return f"{nice} is in {cont}."
        if re.search(r"\b(tell me about|what is|about)\b", s) and len(s.split()) <= 6:
            return f"{nice}: capital {cap}; currency {cur}; continent {cont}."
    return None
