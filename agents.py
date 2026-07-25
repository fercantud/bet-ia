import requests

class DataQualityService:
    @staticmethod
    def calculate_dqi(starter_confirmed: bool, lineup_confirmed: bool, weather_confirmed: bool, odds_fresh: bool, umpire_confirmed: bool) -> dict:
        pitchers_score = 25 if starter_confirmed else 10
        lineup_score = 25 if lineup_confirmed else 10
        weather_score = 20 if weather_confirmed else 5
        odds_score = 20 if odds_fresh else 5
        umpire_score = 10 if umpire_confirmed else 0

        total_score = pitchers_score + lineup_score + weather_score + odds_score + umpire_score

        return {
            "total_score": total_score,
            "breakdown": {
                "Pitchers": f"{pitchers_score}/25",
                "Lineups": f"{lineup_score}/25",
                "Weather": f"{weather_score}/20",
                "Odds": f"{odds_score}/20",
                "Umpire": f"{umpire_score}/10"
            }
        }

class WeatherAgent:
    STADIUM_INFO = {
        "Atlanta Braves": {"coords": (33.89, -84.46), "park_factor": 1.04, "wind_dir": "Out to RF", "hr_factor": 112},
        "Detroit Tigers": {"coords": (42.33, -83.04), "park_factor": 0.96, "wind_dir": "In from CF", "hr_factor": 91},
        "Toronto Blue Jays": {"coords": (43.64, -79.38), "park_factor": 1.01, "wind_dir": "Dome / Closed", "hr_factor": 100},
        "St. Louis Cardinals": {"coords": (38.62, -90.19), "park_factor": 0.98, "wind_dir": "Crosswind L to R", "hr_factor": 94},
        "Cleveland Guardians": {"coords": (41.49, -81.68), "park_factor": 0.97, "wind_dir": "Out to LF", "hr_factor": 95}
    }

    def analyze_weather(self, home_team: str) -> dict:
        info = self.STADIUM_INFO.get(home_team, {"coords": (40.0, -80.0), "park_factor": 1.00, "wind_dir": "Variable", "hr_factor": 100})
        lat, lon = info["coords"]

        try:
            url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true&hourly=relativehumidity_2m"
            res = requests.get(url, timeout=3).json()
            cw = res.get("current_weather", {})
            temp_c = cw.get("temperature", 22)
            wind_speed = cw.get("windspeed", 10)
        except Exception:
            temp_c, wind_speed = 22, 10

        weather_adj = 0.0
        if temp_c > 26 and "Out" in info["wind_dir"]:
            weather_adj += 0.023
        elif temp_c < 12 or "In" in info["wind_dir"]:
            weather_adj -= 0.018

        return {
            "temp": temp_c,
            "wind": wind_speed,
            "park_factor": info["park_factor"],
            "hr_factor": info["hr_factor"],
            "wind_dir": info["wind_dir"],
            "adjustment": weather_adj
        }

class OffenseAgent:
    @staticmethod
    def get_offense_adjustment(home_team: str, away_team: str) -> dict:
        home_wrc = 108
        away_wrc = 98
        net_wrc_diff = home_wrc - away_wrc
        offense_adj = (net_wrc_diff * 0.0015)

        return {
            "home_wrc": home_wrc,
            "away_wrc": away_wrc,
            "adjustment": round(offense_adj, 4)
        }
