# PV Smart Scheduler

Der **PV Smart Scheduler** ist eine intelligente Home Assistant Integration, die große Haushaltsgeräte (wie Waschmaschine, Trockner oder Spülmaschine) automatisiert und präzise auf deinen Solarüberschuss abstimmt.

### Features
* 🧠 **Adaptives Lernen:** Analysiert die Recorder-Historie der letzten Tage und lernt das individuelle Verbrauchsprofil deines Geräts vollautomatisch.
* 📈 **Präzise Vorhersage:** Verrechnet PV-Prognosen mit deiner aktuellen Haus-Basislast, um das perfekte Startfenster zu ermitteln.
* 🌦️ **Wetter-Stabilitätsfaktor:** Rechnet bei unbeständigem Wetter Sicherheitsmargen in die Prognose ein.
* ⚙️ **100% UI-gesteuert:** Bequeme Einrichtung direkt über die Home Assistant Benutzeroberfläche dank Config Flow – komplett ohne YAML.
* 🤖 **LLM-Ready:** Liefert ein sauberes JSON-Attribut (`ai_prompt_context`), das direkt als Kontext an lokale KI-Modelle (Ollama) oder Automatisierungen (n8n) übergeben werden kann.
