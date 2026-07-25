import numpy as np

class MonteCarloEngine:
    def __init__(self, num_simulations: int = 10000):
        self.num_sims = num_simulations

    def simulate_game(self, exp_runs_home: float, exp_runs_away: float, std_home: float = 0.8, std_away: float = 0.8) -> dict:
        """
        Simula N partidos incorporando incertidumbre estocástica en la potencia ofensiva/pitcheo (parámetros) 
        además de la varianza en el resultado de carreras (Poisson).
        """
        # 1. Variabilidad estocástica en los parámetros de entrada por simulación (ej. volatilidad de bullpen/clima)
        sim_exp_home = np.random.normal(exp_runs_home, std_home / np.sqrt(9), self.num_sims)
        sim_exp_away = np.random.normal(exp_runs_away, std_away / np.sqrt(9), self.num_sims)
        
        sim_exp_home = np.maximum(1.0, sim_exp_home)
        sim_exp_away = np.maximum(1.0, sim_exp_away)

        # 2. Generación de carreras usando distribución de Poisson condicional
        home_runs = np.random.poisson(sim_exp_home)
        away_runs = np.random.poisson(sim_exp_away)

        # 3. Resolver empates con ventaja empírica de localía en Extra Innings
        ties = (home_runs == away_runs)
        home_runs[ties] += np.random.choice([0, 1], size=np.sum(ties), p=[0.46, 0.54])

        home_wins = np.sum(home_runs > away_runs)
        prob_home = float(home_wins / self.num_sims)

        # 4. IC95% empírico vía Percentiles de Bootstrap
        # Generar sub-muestras para calcular la dispersión real del modelo
        sample_probs = [np.mean(home_runs[i:i+500] > away_runs[i:i+500]) for i in range(0, self.num_sims, 500)]
        ci_lower = float(np.percentile(sample_probs, 2.5))
        ci_upper = float(np.percentile(sample_probs, 97.5))

        return {
            "p_home": round(prob_home, 4),
            "ci_95": (round(ci_lower, 4), round(ci_upper, 4)),
            "exp_runs_home": round(float(np.mean(home_runs)), 2),
            "exp_runs_away": round(float(np.mean(away_runs)), 2)
        }
