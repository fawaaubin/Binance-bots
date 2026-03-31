# 🤖 Binance Professional Trading Bot v5.0 ULTIMATE

## ✨ Fonctionnalités complètes

### 🧠 Stratégie (5 confirmations avant d'acheter)
| Indicateur | Rôle |
|---|---|
| EMA 50/200 | Filtre de tendance — trade UNIQUEMENT dans le sens du marché |
| RSI (14) | Détecte survente (< 35) et surachat (> 65) |
| MACD (12/26/9) | Confirme le croisement haussier/baissier |
| Bollinger Bands (20) | Prix aux niveaux extrêmes |
| Anti Pump-and-Dump | Détecte mouvements anormaux (+5%/-5% en 1h, volume x3) |

### 🛡️ Gestion du risque
| Paramètre | Valeur |
|---|---|
| Risque / trade | 3% du capital |
| Stop-Loss fixe | -1.5% |
| Trailing Stop | -1.2% depuis le plus haut |
| Take-Profit | +4% |
| Max trades simultanés | 2 (max 1 par paire) |
| Cooldown entre trades | 30 min par paire |
| Alerte balance faible | < 20 USDT |

### ⏰ Fenêtres de trading (UTC)
| Heure | Session | Qualité |
|---|---|---|
| 00h-03h | Asie | ⭐⭐ |
| 08h-12h | Europe | ⭐⭐ |
| **13h-17h** | **Europe+US** | **⭐⭐⭐** |
| 17h-20h | US | ⭐⭐ |
| Autres | Pause | ❌ |
| Weekend | Pause | ❌ |

### 🔁 Fiabilité
- Reconnexion automatique si Binance déconnecte
- Sauvegarde de tous les trades dans `trades_history.csv`
- Rapport journalier automatique sur Telegram
- Surveillance des trades ouverts même pendant les pauses

## 📊 Top 10 paires tradées
BTC, ETH, BNB, SOL, XRP, ADA, DOGE, AVAX, DOT, MATIC

## 🔐 Variables d'environnement
```
BINANCE_API_KEY=ta_cle_api
BINANCE_SECRET_KEY=ta_cle_secrete
TELEGRAM_TOKEN=ton_token_telegram
TELEGRAM_CHAT_ID=ton_chat_id
```

## 🚀 Déploiement Render.com (gratuit)
1. Upload ces fichiers sur GitHub (repo privé)
2. Créer un "Web Service" sur render.com
3. Connecter ton repo GitHub
4. Ajouter les 4 variables d'environnement
5. Deploy !
