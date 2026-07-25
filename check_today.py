from mlb_api import MLBDataFetcher

def show_schedule():
    fetcher = MLBDataFetcher()
    games = fetcher.get_todays_games()

    print("\n==================================================")
    print("             CARTELERA REAL MLB - HOY             ")
    print("==================================================")

    if not games:
        print("No se encontraron partidos para hoy.")
        return

    for g in games:
        status = "CONFIRMADOS" if g["pitchers_confirmed"] else "PENDIENTE"
        print(f"Game ID: {g['game_id']}")
        print(f"Matchup: {g['away_team']} vs {g['home_team']}")
        print(f"Pitchers: {g['away_pitcher']} vs {g['home_pitcher']}")
        print(f"Estado de Lanzadores: {status}")
        print("-" * 50)

if __name__ == "__main__":
    show_schedule()
