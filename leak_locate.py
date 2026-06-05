import numpy as np
from copy import deepcopy
from typing import Dict, List, Optional, Tuple
from models import WaterNetwork, NodeType
from hydraulic import run_hydraulic_with_relaxation
from leak_sim import compute_leak_flow, get_leak_pressure, run_leak_simulation


def compute_base_pressures(network: WaterNetwork, method: str = "gradient"
                           ) -> Dict[str, float]:
    net_copy = deepcopy(network)
    net_copy.leaks.clear()
    try:
        run_hydraulic_with_relaxation(net_copy, method)
    except Exception:
        pass
    return {nid: node.pressure or 0.0 for nid, node in net_copy.nodes.items()}


def compute_sensitivity_matrix(network: WaterNetwork,
                               monitor_nodes: List[str],
                               method: str = "gradient",
                               delta_area: float = 10.0
                               ) -> Tuple[np.ndarray, List[str]]:
    link_ids = sorted(network.links.keys())
    n_monitors = len(monitor_nodes)
    n_links = len(link_ids)

    base_pressures = compute_base_pressures(network, method)

    S = np.zeros((n_monitors, n_links))

    for j, lid in enumerate(link_ids):
        net_copy = deepcopy(network)
        net_copy.leaks.clear()
        net_copy.add_leak(lid, position=0.5, area_mm2=delta_area,
                          pipe_type="metal")

        try:
            run_leak_simulation(net_copy, method)
        except Exception:
            continue

        for i, mnid in enumerate(monitor_nodes):
            if mnid in net_copy.nodes:
                p_with_leak = net_copy.nodes[mnid].pressure or 0.0
                p_base = base_pressures.get(mnid, 0.0)
                S[i, j] = p_base - p_with_leak

    return S, link_ids


def screen_suspect_links(S: np.ndarray, link_ids: List[str],
                         deviation: np.ndarray,
                         top_k: int = 10) -> List[str]:
    if S.shape[0] == 0 or S.shape[1] == 0:
        return link_ids[:top_k]

    scores = np.zeros(S.shape[1])
    for j in range(S.shape[1]):
        col = S[:, j]
        col_norm = np.linalg.norm(col)
        if col_norm > 1e-12:
            scores[j] = np.abs(np.dot(col, deviation)) / col_norm
        else:
            scores[j] = 0.0

    top_indices = np.argsort(scores)[::-1][:top_k]
    return [link_ids[i] for i in top_indices]


def genetic_algorithm_search(network: WaterNetwork,
                             suspect_links: List[str],
                             monitor_nodes: List[str],
                             measured_pressures: Dict[str, float],
                             method: str = "gradient",
                             pop_size: int = 50,
                             generations: int = 200,
                             crossover_rate: float = 0.8,
                             mutation_rate: float = 0.1
                             ) -> Dict:
    n_suspects = len(suspect_links)
    n_genes = n_suspects * 2

    base_pressures = compute_base_pressures(network, method)

    def decode_chromosome(chromosome: np.ndarray) -> List[Dict]:
        leaks = []
        for i in range(n_suspects):
            area = chromosome[i * 2]
            position = chromosome[i * 2 + 1]
            if area > 0.5:
                leaks.append({
                    "link_id": suspect_links[i],
                    "area_mm2": area * 100.0,
                    "position": position,
                })
        return leaks

    def fitness(chromosome: np.ndarray) -> float:
        leaks = decode_chromosome(chromosome)
        if not leaks:
            residual = 0.0
            for mnid in monitor_nodes:
                p_meas = measured_pressures.get(mnid, 0.0)
                p_base = base_pressures.get(mnid, 0.0)
                residual += (p_meas - p_base) ** 2
            return residual

        net_copy = deepcopy(network)
        net_copy.leaks.clear()
        for leak in leaks:
            net_copy.add_leak(leak["link_id"],
                              leak["position"],
                              leak["area_mm2"],
                              "metal")

        try:
            run_leak_simulation(net_copy, method)
        except Exception:
            return 1e10

        residual = 0.0
        for mnid in monitor_nodes:
            p_meas = measured_pressures.get(mnid, 0.0)
            p_sim = net_copy.nodes[mnid].pressure if mnid in net_copy.nodes else 0.0
            residual += (p_meas - p_sim) ** 2
        return residual

    population = np.random.rand(pop_size, n_genes)
    population[:, 1::2] = np.random.rand(pop_size, n_suspects)

    fitness_values = np.array([fitness(ind) for ind in population])

    best_idx = np.argmin(fitness_values)
    best_chromosome = population[best_idx].copy()
    best_fitness = fitness_values[best_idx]

    for gen in range(generations):
        sorted_indices = np.argsort(fitness_values)
        population = population[sorted_indices]
        fitness_values = fitness_values[sorted_indices]

        new_population = np.zeros_like(population)
        elite_count = max(2, pop_size // 10)
        new_population[:elite_count] = population[:elite_count]

        for i in range(elite_count, pop_size):
            tournament1 = np.random.randint(0, pop_size // 2)
            tournament2 = np.random.randint(0, pop_size // 2)
            if fitness_values[tournament1] < fitness_values[tournament2]:
                parent1 = population[tournament1]
            else:
                parent1 = population[tournament2]

            tournament3 = np.random.randint(0, pop_size // 2)
            tournament4 = np.random.randint(0, pop_size // 2)
            if fitness_values[tournament3] < fitness_values[tournament4]:
                parent2 = population[tournament3]
            else:
                parent2 = population[tournament4]

            if np.random.rand() < crossover_rate:
                crossover_point = np.random.randint(1, n_genes)
                child = np.concatenate([
                    parent1[:crossover_point],
                    parent2[crossover_point:]
                ])
            else:
                child = parent1.copy()

            for g in range(n_genes):
                if np.random.rand() < mutation_rate:
                    if g % 2 == 0:
                        child[g] = np.random.rand()
                    else:
                        child[g] = np.random.rand()

            new_population[i] = child

        population = new_population
        fitness_values = np.array([fitness(ind) for ind in population])

        current_best_idx = np.argmin(fitness_values)
        if fitness_values[current_best_idx] < best_fitness:
            best_fitness = fitness_values[current_best_idx]
            best_chromosome = population[current_best_idx].copy()

    leaks = decode_chromosome(best_chromosome)
    active_leaks = [l for l in leaks if l["area_mm2"] > 1.0]

    max_possible_residual = sum(
        (measured_pressures.get(mnid, 0.0) - base_pressures.get(mnid, 0.0)) ** 2
        for mnid in monitor_nodes
    )
    if max_possible_residual > 0:
        confidence = max(0.0, 1.0 - best_fitness / max_possible_residual) * 100
    else:
        confidence = 0.0

    return {
        "leaks": active_leaks,
        "residual": best_fitness,
        "confidence": min(confidence, 100.0),
        "best_chromosome": best_chromosome,
    }


def run_leak_localization(network: WaterNetwork,
                          monitor_nodes: List[str],
                          measured_pressures: Dict[str, float],
                          method: str = "gradient",
                          top_k: int = 10) -> Dict:
    base_pressures = compute_base_pressures(network, method)

    deviation = np.array([
        base_pressures.get(mnid, 0.0) - measured_pressures.get(mnid, 0.0)
        for mnid in monitor_nodes
    ])

    S, link_ids = compute_sensitivity_matrix(network, monitor_nodes, method)

    suspect_links = screen_suspect_links(S, link_ids, deviation, top_k)

    ga_result = genetic_algorithm_search(
        network, suspect_links, monitor_nodes,
        measured_pressures, method
    )

    return {
        "sensitivity_matrix": S,
        "link_ids": link_ids,
        "suspect_links": suspect_links,
        "base_pressures": base_pressures,
        "deviation": deviation,
        "ga_result": ga_result,
        "leaks": ga_result["leaks"],
        "confidence": ga_result["confidence"],
        "residual": ga_result["residual"],
    }
