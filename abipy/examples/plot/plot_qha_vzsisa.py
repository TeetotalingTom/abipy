#!/usr/bin/env python
r"""
Quasi-harmonic approximation with v-ZSISA
=========================================

This example shows how to use the GSR.nc and PHDOS.nc files computed with different volumes
to compute thermodynamic properties within the v-ZSISA approximation.
"""
import os
import abipy.data as abidata

from abipy.dfpt.vzsisa import Vzsisa

# Root points to the directory in the git submodule with the output results.
root = os.path.join(abidata.dirpath, "data_v-ZSISA-QHA.git", "Si_v_ZSISA_approximation")

strains = [96, 98, 100, 102, 104, 106]
strains2 = [98, 100, 102, 104, 106] # EinfVib4(D)
#strains2 = [96, 98, 100, 102, 104] # EinfVib4(S)
#strains2 = [100, 102, 104] # EinfVib2(D)

gsr_paths = [os.path.join(root, "scale_{:d}_GSR.nc".format(s)) for s in strains]
ddb_paths = [os.path.join(root, "scale_{:d}_GSR_DDB".format(s)) for s in strains]
phdos_paths = [os.path.join(root, "scale_{:d}_PHDOS.nc".format(s)) for s in strains2]

qha = Vzsisa.from_ddb_phdos_files(ddb_paths, phdos_paths)
tstart, tstop, num = 0, 800, 101

#%%
# Plot BO Energies as a function of volume for different T
qha.plot_bo_energies(tstart=tstart, tstop=tstop, num=11)

#%%
# Plot Volume as a function of T
qha.plot_vol_vs_t(tstart=tstart, tstop=tstop, num=num)

#%%
# Plot Lattice as a function of T
qha.plot_abc_vs_t(tstart=tstart, tstop=tstop, num=num)

#%%
# Plot Lattice as a function of T
qha.plot_abc_vs_t(tstart=tstart, tstop=tstop, num=num, lattice="b")

#%%
# Plot Volumetric thermal expansion coefficient as a function of T
qha.plot_thermal_expansion_coeff(tstart=tstart, tstop=tstop, num=num)

#%%
# Plot Thermal expansion coefficient as a function of T
qha.plot_thermal_expansion_coeff_abc(tstop=tstop, tstart=tstart, num=num)

#%%
# Plot Angles as a function of T
qha.plot_angles_vs_t(tstart=tstart, tstop=tstop, num=num)

#%%
#
# Plot Volume as a function of T. 4th order polinomial
qha.plot_vol_vs_t_4th(tstart=tstart, tstop=tstop, num=num)

#%%
# Plot Lattice as a function of T. 4th order polinomial
qha.plot_abc_vs_t_4th(tstart=tstart, tstop=tstop, num=num, lattice="a")

#%%
# Plot Lattice as a function of T. 4th order polinomial
qha.plot_abc_vs_t_4th(tstart=tstart, tstop=tstop)

#%%
# Plot Volumetric thermal expansion coefficient as a function of T
qha.plot_thermal_expansion_coeff_4th(tref=293)

#%%
# Plot Thermal expansion coefficient as a function of T
qha.plot_thermal_expansion_coeff_abc_4th(tstart=tstart, tstop=tstop, num=num, tref=293)

#%%
# Plot Angles as a function of T.
qha.plot_angles_vs_t_4th(tstart=tstart, tstop=tstop, num=num, angle=3)

#%%
# Create plotter to plot all the phonon DOS.
phdos_plotter = qha.get_phdos_plotter()
phdos_plotter.combiplot()
