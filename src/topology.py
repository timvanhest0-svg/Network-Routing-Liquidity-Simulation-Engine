from __future__ import annotations
import numpy as np
def degree_moments(gamma, n_nodes:int):
    if n_nodes<2: raise ValueError("n_nodes must be at least 2")
    g=np.asarray(gamma,float)
    if np.any(~np.isfinite(g)) or np.any(g<=0): raise ValueError("gamma must be positive and finite")
    k=np.arange(1,n_nodes+1,dtype=float)
    w=k**(-g[...,None]); p=w/w.sum(axis=-1,keepdims=True)
    return (p*k).sum(axis=-1),(p*k**2).sum(axis=-1)
def liquidity_multipliers(gamma,n_nodes:int):
    ek,ek2=degree_moments(gamma,n_nodes)
    return ek,ek2/ek-1.0
def make_multiplier_grids(n_nodes:int,grid_size:int=5000):
    grid=np.linspace(.01,20.,grid_size)
    direct,indirect=liquidity_multipliers(grid,n_nodes)
    return grid,direct,indirect
