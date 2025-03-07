# coding: utf-8
"""
Interface to the ABIWAN netcdf file produced by abinit when calling wannier90 in library mode.
Inspired to the Fortran version of wannier90.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import time

from tabulate import tabulate
from monty.string import marquee
from monty.functools import lazy_property
from monty.termcolor import cprint
from abipy.core.structure import Structure
from abipy.core.mixins import AbinitNcFile, Has_Header, Has_Structure, Has_ElectronBands, NotebookWriter
from abipy.core.kpoints import Kpath, IrredZone
from abipy.core.skw import ElectronInterpolator
from abipy.abio.robots import Robot
from abipy.tools.plotting import add_fig_kwargs, get_ax_fig_plt, set_grid_legend #, get_axarray_fig_plt
from abipy.tools.typing import Figure
from abipy.electrons.ebands import ElectronBands, ElectronsReader, ElectronBandsPlotter, RobotWithEbands


class AbiwanFile(AbinitNcFile, Has_Header, Has_Structure, Has_ElectronBands, NotebookWriter):
    """
    File produced by Abinit with the unitary matrices obtained by calling wannier90 in library mode.

    Usage example:

    .. code-block:: python

        with abilab.abiopen("foo_ABIWAN.nc") as abiwan:
            print(abiwan)

    .. rubric:: Inheritance Diagram
    .. inheritance-diagram:: AbiwanFile
    """

    @classmethod
    def from_file(cls, filepath: str) -> AbiwanFile:
        """Initialize the object from a netcdf file."""
        return cls(filepath)

    def __init__(self, filepath: str):
        super().__init__(filepath)
        self.r = AbiwanReader(filepath)

        # Number of bands actually used to construct the Wannier functions
        self.num_bands_spin = self.r.read_value("num_bands")

    @lazy_property
    def nwan_spin(self) -> np.ndarray:
        """Number of Wannier functions for each spin."""
        return self.r.read_value("nwan")

    @lazy_property
    def mwan(self) -> int:
        """
        Max number of Wannier functions over spins, i.e max(nwan_spin)
        Used to dimension arrays.
        """
        return self.r.read_dimvalue("mwan")

    @lazy_property
    def nntot(self) -> int:
        """Number of k-point neighbours."""
        return int(self.r.read_value("nntot"))

    @lazy_property
    def bands_in(self) -> np.ndarray:
        """
        [nsppol, mband] logical array. Set to True if (spin, band) is included
        in the calculation. Set by exclude_bands
        """
        return self.r.read_value("band_in_int").astype(bool)

    @lazy_property
    def lwindow(self) -> np.ndarray:
        """
        [nsppol, nkpt, max_num_bands] array. Only if disentanglement.
        True if this band at this k-point lies within the outer window.
        """
        return self.r.read_value("lwindow_int").astype(bool)

    #@lazy_property
    #def ndimwin(self):
    #    """
    #    [nsppol, nkpt] array giving the number of bands inside the outer window for each k-point and spin.
    #    """
    #    return self.r.read_value("ndimwin")

    @lazy_property
    def have_disentangled_spin(self) -> np.ndarray:
        """[nsppol] bool array. Whether disentanglement has been performed."""
        #return self.r.read_value("have_disentangled_spin").astype(bool)
        # TODO: Exclude bands
        return self.nwan_spin != self.num_bands_spin

    @lazy_property
    def wann_centers(self) -> np.ndarray:
        """[nsppol, mwan, 3] array with Wannier centers in Ang."""
        return self.r.read_value("wann_centres")

    @lazy_property
    def wann_spreads(self) -> np.ndarray:
        """[nsppol, mwan] array with spreads in Ang^2"""
        return self.r.read_value("wann_spreads")

    @lazy_property
    def irvec(self) -> np.ndarray:
        """
        [nrpts, 3] array with the lattice vectors in the Wigner-Seitz cell
        in the basis of the lattice vectors defining the unit cell
        """
        return self.r.read_value("irvec")

    @lazy_property
    def ndegen(self) -> np.ndarray:
        """
        [nrpts] array with the degeneracy of each point.
        It will be weighted using 1 / ndegen[ir]
        """
        return self.r.read_value("ndegen")

    @lazy_property
    def params(self) -> dict:
        """dict with parameters that might be subject to convergence studies."""
        od = self.get_ebands_params()
        # TODO
        return od

    def __str__(self) -> str:
        """String representation."""
        return self.to_string()

    def to_string(self, verbose: int = 0) -> str:
        """String representation with verbosity level verbose."""
        lines = []; app = lines.append

        app(marquee("File Info", mark="="))
        app(self.filestat(as_string=True))
        app("")
        app(self.structure.to_string(verbose=verbose, title="Structure"))
        app("")
        app(self.ebands.to_string(title="Electronic Bands", with_structure=False, with_kpoints=True, verbose=verbose))
        app("")
        app(marquee("Wannier90 Results", mark="="))

        for spin in range(self.nsppol):
            if self.nsppol == 2: app("For spin: %d" % spin)
            app("No of Wannier functions: %d, No bands: %d, Number of k-point neighbours: %d" %
                (self.nwan_spin[spin], self.num_bands_spin[spin], self.nntot))
            app("Disentanglement: %s, exclude_bands: %s" %
                (self.have_disentangled_spin[spin], "no" if np.all(self.bands_in[spin]) else "yes"))
            app("")
            table = [["WF_index", "Center", "Spread"]]
            for iwan in range(self.nwan_spin[spin]):
                table.append([iwan,
                             "%s" % np.array2string(self.wann_centers[spin, iwan], precision=5),
                             "%.3f" % self.wann_spreads[spin, iwan]])
            app(tabulate(table, tablefmt="plain"))
            app("")

        if verbose and np.any(self.have_disentangled_spin):
            app(marquee("Lwindow", mark="="))
            app("[nsppol, nkpt, max_num_bands] array. True if state lies within the outer window.\n")
            for spin in range(self.nsppol):
                if self.nsppol == 2: app("For spin: %d" % spin)
                for ik in range(self.nkpt):
                    app("For ik: %d, %s" % (ik, self.lwindow[spin, ik]))
                app("")

        if verbose and np.any(self.bands_in):
            app(marquee("Bands_in", mark="="))
            app("[nsppol, mband] array. True if (spin, band) is included in the calculation. Set by exclude_bands.\n")
            for spin in range(self.nsppol):
                if self.nsppol == 2: app("For spin: %d" % spin)
                app("%s" % str(self.bands_in[spin]))
                app("")

        if verbose > 1:
            app("")
            app(self.hdr.to_string(verbose=verbose, title="Abinit Header"))
            if verbose >= 2:
                app("irvec and ndegen")
                for r, n in zip(self.irvec, self.ndegen):
                    app("%s %s" % (r, n))

        return "\n".join(lines)

    def close(self) -> None:
        """Close file."""
        self.r.close()

    @lazy_property
    def ebands(self) -> ElectronBands:
        """|ElectronBands| object."""
        return self.r.read_ebands()

    @property
    def structure(self) -> Structure:
        """|Structure| object."""
        return self.ebands.structure

    @lazy_property
    def hwan(self) -> HWanR:
        """
        Construct the matrix elements of the KS Hamiltonian in real space
        """
        start = time.time()

        nrpts, num_kpts = len(self.irvec), self.ebands.nkpt
        kfrac_coords = self.ebands.kpoints.frac_coords
        # Init datastructures needed by HWanR
        spin_rmn = [None] * self.nsppol
        spin_vmatrix = np.empty((self.nsppol, num_kpts), dtype=object)

        #kptopt = self.read.read_value("kptopt")
        #has_timrev =

        # Read unitary matrices from file.
        # Here be very careful with F --> C because we have to transpose.
        # complex U_matrix[nsppol, nkpt, mwan, mwan]
        u_matrix = self.r.read_value("U_matrix", cmode="c")

        # complex U_matrix_opt[nsppol, mkpt, mwan, mband]
        if np.any(self.have_disentangled_spin):
            u_matrix_opt = self.r.read_value("U_matrix_opt", cmode="c")

        for spin in range(self.nsppol):
            num_wan = self.nwan_spin[spin]

            # Real-space Hamiltonian H(R) is calculated by Fourier
            # transforming H(q) defined on the ab-initio reciprocal mesh
            HH_q = np.zeros((num_kpts, num_wan, num_wan), dtype=complex)

            for ik in range(num_kpts):
                eigs_k = self.ebands.eigens[spin, ik]
                # May have num_wan != mwan
                uk = u_matrix[spin, ik][:num_wan, :num_wan].transpose().copy()

                # Calculate the matrix that describes the combined effect of
                # disentanglement and maximal localization. This is the combination
                # that is most often needed for interpolation purposes
                # FIXME: problem with netcdf file
                if not self.have_disentangled_spin[spin]:
                    # [num_wann, num_wann] matrices, bands_in needed if exclude_bands
                    hks = np.diag(eigs_k[self.bands_in[spin]])
                    v_matrix = uk
                else:
                    # Select bands within the outer window
                    # TODO: Test if bands_in?
                    mask = self.lwindow[spin, ik]
                    hks = np.diag(eigs_k[mask])
                    #v_matrix = u_matrix_opt[spin, ik][:num_wan, mask].transpose() @ uk
                    v_matrix = np.matmul(u_matrix_opt[spin, ik][:num_wan, mask].transpose(), uk)

                #HH_q[ik] = v_matrix.transpose().conjugate() @ hks @ v_matrix
                HH_q[ik] = np.matmul(v_matrix.transpose().conjugate(), np.matmul(hks, v_matrix))
                spin_vmatrix[spin, ik] = v_matrix

            # Fourier transform Hamiltonian in the wannier-gauge representation.
            # O_ij(R) = (1/N_kpts) sum_q e^{-iqR} O_ij(q)
            rmn = np.zeros((nrpts, num_wan, num_wan), dtype=complex)
            j2pi = 2.0j * np.pi

            #for ir in range(nrpts):
            #   for ik, kfcs in enumerate(kfrac_coords):
            #      jqr = j2pi * np.dot(kfcs, self.irvec[ir])
            #      rmn[ir] += np.exp(-jqr) * HH_q[ik]
            #rmn *= (1.0 / num_kpts)

            for ik, kfcs in enumerate(kfrac_coords):
                jqr = j2pi * np.dot(self.irvec, kfcs)
                phases = np.exp(-jqr)
                rmn += phases[:, None, None] * HH_q[ik]
            rmn *= (1.0 / num_kpts)

            # Save results
            spin_rmn[spin] = rmn

        print("HWanR built in %.3f (s)" % (time.time() - start))
        return HWanR(self.structure, self.nwan_spin, spin_vmatrix, spin_rmn, self.irvec, self.ndegen)

    def interpolate_ebands(self, vertices_names=None, line_density=20,
                           ngkpt=None, shiftk=(0, 0, 0), kpoints=None) -> ElectronBands:
        """
        Build new |ElectronBands| object by interpolating the KS Hamiltonian with Wannier functions.
        Supports k-path via (vertices_names, line_density), IBZ mesh defined by ngkpt and shiftk
        or input list of kpoints.

        Args:
            vertices_names: Used to specify the k-path for the interpolated QP band structure
                List of tuple, each tuple is of the form (kfrac_coords, kname) where
                kfrac_coords are the reduced coordinates of the k-point and kname is a string with the name of
                the k-point. Each point represents a vertex of the k-path. ``line_density`` defines
                the density of the sampling. If None, the k-path is automatically generated according
                to the point group of the system.
            line_density: Number of points in the smallest segment of the k-path. Used with ``vertices_names``.
            ngkpt: Mesh divisions. Used if bands should be interpolated in the IBZ.
            shiftk: Shifts for k-meshs. Used with ngkpt.
            kpoints: |KpointList| object taken e.g from a previous ElectronBands.
                Has precedence over vertices_names and line_density.
        """
        # Need KpointList object.
        if kpoints is None:
            if ngkpt is not None:
                # IBZ sampling
                kpoints = IrredZone.from_ngkpt(self.structure, ngkpt, shiftk, kptopt=1, verbose=0)
            else:
                # K-Path
                if vertices_names is None:
                    vertices_names = [(k.frac_coords, k.name) for k in self.structure.hsym_kpoints]
                kpoints = Kpath.from_vertices_and_names(self.structure, vertices_names, line_density=line_density)

        nk = len(kpoints)
        eigens = np.zeros((self.nsppol, nk, self.mwan))

        # Interpolate Hamiltonian for each kpoint and spin.
        start = time.time()
        write_warning = True
        for spin in range(self.nsppol):
            num_wan = self.nwan_spin[spin]
            for ik, kpt in enumerate(kpoints):
                oeigs = self.hwan.eval_sk(spin, kpt.frac_coords)
                eigens[spin, ik, :num_wan] = oeigs
                if num_wan < self.mwan:
                    # May have different number of wannier functions if nsppol == 2.
                    # Here I use the last value to fill eigens matrix (not very clean but oh well).
                    eigens[spin, ik, num_wan:self.mwan] = oeigs[-1]
                    if write_warning:
                        cprint("Different number wannier functions for spin. Filling last bands with oeigs[-1]",
                               color="yellow")
                        write_warning = False

        print("Interpolation completed in %.3f [s]" % (time.time() - start))
        occfacts = np.zeros_like(eigens)

        return ElectronBands(self.structure, kpoints, eigens, self.ebands.fermie,
                             occfacts, self.ebands.nelect, self.nspinor, self.nspden,
                             smearing=self.ebands.smearing)

    @add_fig_kwargs
    def plot_with_ebands(self, ebands_kpath,
                         ebands_kmesh=None, method="gaussian", step: float = 0.05, width: float = 0.1, **kwargs) -> Figure:
        """
        Receive an ab-initio electronic strucuture, interpolate the energies on the same list of k-points
        and compare the two band structures.

        Args:
            ebands_kpath: ab-initio band structure on a k-path (either ElectroBands object or object providing it).
            ebands_kmesh: ab-initio band structure on a k-mesh (either ElectroBands object or object providing it).
                If not None the ab-initio and the wannier-interpolated electron DOS are computed and plotted.
            method: Integration scheme for DOS.
            step: Energy step (eV) of the linear mesh for DOS computation.
            width: Standard deviation (eV) of the gaussian for DOS computation.
        """
        ebands_kpath = ElectronBands.as_ebands(ebands_kpath)
        wan_ebands_kpath = self.interpolate_ebands(kpoints=ebands_kpath.kpoints)

        key_edos = None
        if ebands_kmesh is not None:
            # Compute ab-initio and interpolated e-DOS
            ebands_kmesh = ElectronBands.as_ebands(ebands_kmesh)
            if not ebands_kmesh.kpoints.is_ibz:
                raise ValueError("ebands_kmesh should have k-points in the IBZ!")
            ksampling = ebands_kmesh.kpoints.ksampling
            ngkpt, shifts = ksampling.mpdivs, ksampling.shifts
            if ngkpt is None:
                raise ValueError("Non diagonal k-meshes are not supported!")

            wan_ebands_kmesh = self.interpolate_ebands(ngkpt=ngkpt, shiftk=shifts)

            edos_kws = dict(method=method, step=step, width=width)
            edos = ebands_kmesh.get_edos(**edos_kws)
            wan_edos = wan_ebands_kmesh.get_edos(**edos_kws)
            key_edos = [("ab-initio", edos), ("interpolated", wan_edos)]

        key_ebands = [("ab-initio", ebands_kpath), ("interpolated", wan_ebands_kpath)]
        plotter = ElectronBandsPlotter(key_ebands=key_ebands, key_edos=key_edos)

        linestyle_dict = {
            "ab-initio": dict(color="red", marker="o"),
            "interpolated": dict(color="blue", ls="-"),
        }
        # Add common style options.
        common_opts = dict(markersize=2, lw=1)

        for d in linestyle_dict.values():
            d.update(**common_opts)

        return plotter.combiplot(linestyle_dict=linestyle_dict, **kwargs)

    def yield_figs(self, **kwargs):  # pragma: no cover
        """
        This function *generates* a predefined list of matplotlib figures with minimal input from the user.
        """
        yield self.interpolate_ebands().plot(show=False)
        yield self.hwan.plot(show=False)

    def write_notebook(self, nbpath=None) -> str:
        """
        Write a jupyter_ notebook to ``nbpath``. If nbpath is None, a temporay file in the current
        working directory is created. Return path to the notebook.
        """
        nbformat, nbv, nb = self.get_nbformat_nbv_nb(title=None)

        nb.cells.extend([
            nbv.new_code_cell("abiwan = abilab.abiopen('%s')" % self.filepath),
            nbv.new_code_cell("print(abiwan.to_string(verbose=0))"),
            nbv.new_code_cell("abiwan.ebands.plot();"),
            nbv.new_code_cell("abiwan.ebands.kpoints.plot();"),
            nbv.new_code_cell("abiwan.hwan.plot();"),
            nbv.new_code_cell("ebands_kpath = abiwan.interpolate_ebands()"),
            nbv.new_code_cell("ebands_kpath.plot();"),
            nbv.new_code_cell("ebands_kmesh = abiwan.interpolate_ebands(ngkpt=[8, 8, 8])"),
            nbv.new_code_cell("ebands_kpath.plot_with_edos(ebands_kmesh.get_edos());"),
        ])

        return self._write_nb_nbpath(nb, nbpath)


class HWanR(ElectronInterpolator):
    """
    This object represents the KS Hamiltonian in the wannier-gauge representation.
    It provides low-level methods to interpolate the KS eigenvalues, and a high-level API
    to interpolate band structures and plot the decay of the matrix elements <0n|H|Rm> in real space.
    """

    def __init__(self, structure, nwan_spin, spin_vmatrix, spin_rmn, irvec, ndegen):
        self.structure = structure
        self.nwan_spin = nwan_spin
        self.spin_vmatrix = spin_vmatrix
        self.spin_rmn = spin_rmn
        self.irvec = irvec
        self.ndegen = ndegen
        self.nrpts = len(ndegen)
        self.nsppol = len(nwan_spin)
        assert self.nsppol == len(self.spin_rmn)
        assert len(self.irvec) == self.nrpts
        for spin in range(self.nsppol):
            assert len(self.spin_rmn[spin]) == self.nrpts

        # To call spglib
        self.cell = (self.structure.lattice.matrix, self.structure.frac_coords, self.structure.atomic_numbers)
        self.has_timrev = True
        self.verbose = 0
        self.nband = nwan_spin[0]
        #self.nelect

    def eval_sk(self, spin: int, kpt, der1=None, der2=None) -> np.ndarray:
        """
        Interpolate eigenvalues for all bands at a given (spin, k-point).
        Optionally compute gradients and Hessian matrices.

        Args:
            spin: Spin index.
            kpt: K-point in reduced coordinates.
            der1: If not None, ouput gradient is stored in der1[nband, 3].
            der2: If not None, output Hessian is der2[nband, 3, 3].

        Return:
            oeigs[nband]
        """
        if der1 is not None or der2 is not None:
            raise NotImplementedError("Derivatives are not coded")

        # O_ij(k) = sum_R e^{+ik.R}*O_ij(R)
        j2pi = 2.0j * np.pi
        jrk = j2pi * np.dot(self.irvec, kpt)
        phases = np.exp(jrk) / self.ndegen
        hk_ij = (self.spin_rmn[spin] * phases[:, None, None]).sum(axis=0)
        oeigs, _ = np.linalg.eigh(hk_ij)

        return oeigs

    @add_fig_kwargs
    def plot(self, ax=None, fontsize=8, yscale="log", **kwargs) -> Figure:
        """
        Plot the matrix elements of the KS Hamiltonian in real space in the Wannier Gauge.

        Args:
            ax: |matplotlib-Axes| or None if a new figure should be created.
            fontsize: fontsize for legends and titles
            yscale: Define scale for y-axis.
            kwargs: options passed to ``ax.plot``.
        """
        # Sort R-points by length and build sortmap.
        irs = [ir for ir in enumerate(self.structure.lattice.norm(self.irvec))]
        items = sorted(irs, key=lambda t: t[1])
        sortmap = np.array([item[0] for item in items])
        rvals = np.array([item[1] for item in items])

        ax, fig, plt = get_ax_fig_plt(ax=ax)

        marker_spin = {0: "^", 1: "v"}
        with_legend = False
        for spin in range(self.nsppol):
            amax_r = [np.abs(self.spin_rmn[spin][ir]).max() for ir in range(self.nrpts)]
            amax_r = [amax_r[i] for i in sortmap]
            label = kwargs.get("label", None)
            if label is not None:
                label = "spin: %d" % spin if self.nsppol == 2 else None
            if label: with_legend = True
            ax.plot(rvals, amax_r, marker=marker_spin[spin],
                    lw=kwargs.get("lw", 2),
                    color=kwargs.get("color", "k"),
                    markeredgecolor="r",
                    markerfacecolor="r",
                    label=label)

            ax.set_yscale(yscale)

        set_grid_legend(ax, fontsize, xlabel=r"$|R|$ (Ang)", ylabel=r"$Max |H^W_{ij}(R)|$", legend=with_legend)

        return fig


class AbiwanReader(ElectronsReader):
    """
    This object reads the results stored in the ABIWAN file produced by ABINIT after having
    called wannier90 in library mode.
    It provides helper function to access the most important quantities.

    .. rubric:: Inheritance Diagram
    .. inheritance-diagram:: AbiwanReader
    """


class AbiwanRobot(Robot, RobotWithEbands):
    """
    This robot analyzes the results contained in multiple ABIWAN.nc files.

    .. rubric:: Inheritance Diagram
    .. inheritance-diagram:: AbiwanRobot
    """
    EXT = "ABIWAN"

    def get_dataframe(self, with_geo: bool = True, abspath: bool = False, funcs=None, **kwargs) -> pd.DataFrame:
        """
        Return a |pandas-DataFrame| with the most important Wannier90 results and the filenames as index.

        Args:
            with_geo: True if structure info should be added to the dataframe.
            abspath: True if paths in index should be absolute. Default: Relative to getcwd().

        kwargs:
            attrs: List of additional attributes of the |GsrFile| to add to the DataFrame.
            funcs: Function or list of functions to execute to add more data to the DataFrame.
                Each function receives a |GsrFile| object and returns a tuple (key, value)
                where key is a string with the name of column and value is the value to be inserted.
        """
        # TODO
        # Add attributes specified by the users
        #attrs = [
        #    "energy", "pressure", "max_force",
        #    "ecut", "pawecutdg",
        #    "tsmear", "nkpt",
        #    "nsppol", "nspinor", "nspden",
        #] + kwargs.pop("attrs", [])

        rows, row_names = [], []
        for label, abiwan in self.items():
            row_names.append(label)
            d = {}

            # Add info on structure.
            if with_geo:
                d.update(abiwan.structure.get_dict4pandas(with_spglib=True))

            #for aname in attrs:
            #    if aname == "nkpt":
            #        value = len(abiwan.ebands.kpoints)
            #    else:
            #        value = getattr(abiwan, aname, None)
            #        if value is None: value = getattr(abiwan.ebands, aname, None)
            #    d[aname] = value

            # Execute functions
            if funcs is not None: d.update(self._exec_funcs(funcs, abiwan))
            rows.append(d)

        row_names = row_names if not abspath else self._to_relpaths(row_names)
        return pd.DataFrame(rows, index=row_names, columns=list(rows[0].keys()))

    @add_fig_kwargs
    def plot_hwanr(self, ax=None, colormap="jet", fontsize=8, **kwargs) -> Figure:
        """
        Plot the matrix elements of the KS Hamiltonian in real space in the Wannier Gauge on the same Axes.

        Args:
            ax: |matplotlib-Axes| or None if a new figure should be created.
            colormap: matplotlib color map.
            fontsize: fontsize for legends and titles
        """
        ax, fig, plt = get_ax_fig_plt(ax=ax)
        cmap = plt.get_cmap(colormap)
        for i, abiwan in enumerate(self.abifiles):
            abiwan.hwan.plot(ax=ax, fontsize=fontsize, color=cmap(i / len(self)), show=False)

        return fig

    def get_interpolated_ebands_plotter(self, vertices_names=None, knames=None, line_density=20,
                                        ngkpt=None, shiftk=(0, 0, 0), kpoints=None, **kwargs) -> ElectronBandsPlotter:
        """
        Args:
            vertices_names: Used to specify the k-path for the interpolated QP band structure
                It's a list of tuple, each tuple is of the form (kfrac_coords, kname) where
                kfrac_coords are the reduced coordinates of the k-point and kname is a string with the name of
                the k-point. Each point represents a vertex of the k-path. ``line_density`` defines
                the density of the sampling. If None, the k-path is automatically generated according
                to the point group of the system.
            knames: List of strings with the k-point labels defining the k-path. It has precedence over `vertices_names`.
            line_density: Number of points in the smallest segment of the k-path. Used with ``vertices_names``.
            ngkpt: Mesh divisions. Used if bands should be interpolated in the IBZ.
            shiftk: Shifts for k-meshs. Used with ngkpt.
            kpoints: |KpointList| object taken e.g from a previous ElectronBands.
                Has precedence over vertices_names and line_density.
        """
        diff_str = self.has_different_structures()
        if diff_str: cprint(diff_str, color="yellow")

        # Need KpointList object (assuming same structures in the Robot)
        nc0 = self.abifiles[0]
        if kpoints is None:
            if ngkpt is not None:
                # IBZ sampling
                kpoints = IrredZone.from_ngkpt(nc0.structure, ngkpt, shiftk, kptopt=1, verbose=0)
            else:
                # K-Path
                if knames is not None:
                    kpoints = Kpath.from_names(nc0.structure, knames, line_density=line_density)
                else:
                    if vertices_names is None:
                        vertices_names = [(k.frac_coords, k.name) for k in nc0.structure.hsym_kpoints]
                    kpoints = Kpath.from_vertices_and_names(nc0.structure, vertices_names, line_density=line_density)

        plotter = ElectronBandsPlotter()
        for label, abiwan in self.items():
            plotter.add_ebands(label, abiwan.interpolate_ebands(kpoints=kpoints))

        return plotter

    def yield_figs(self, **kwargs):  # pragma: no cover
        """
        This function *generates* a predefined list of matplotlib figures with minimal input from the user.
        Used in abiview.py to get a quick look at the results.
        """
        p = self.get_eband_plotter()
        yield p.combiplot(show=False)
        yield p.gridplot(show=False)
        yield self.plot_hwanr(show=False)

    def write_notebook(self, nbpath=None) -> str:
        """
        Write a jupyter_ notebook to ``nbpath``. If nbpath is None, a temporay file in the current
        working directory is created. Return path to the notebook.
        """
        nbformat, nbv, nb = self.get_nbformat_nbv_nb(title=None)

        args = [(l, f.filepath) for l, f in self.items()]
        nb.cells.extend([
            nbv.new_code_cell("robot = abilab.AbiwanRobot(*%s)\nrobot.trim_paths()\nrobot" % str(args)),
            nbv.new_code_cell("robot.get_dataframe()"),
            nbv.new_code_cell("robot.plot_hwanr();"),
            nbv.new_code_cell("ebands_plotter = robot.get_interpolated_ebands_plotter()"),
            nbv.new_code_cell("ebands_plotter.ipw_select_plot()"),
        ])

        # Mixins
        #nb.cells.extend(self.get_baserobot_code_cells())
        #nb.cells.extend(self.get_ebands_code_cells())wannier90.wout

        return self._write_nb_nbpath(nb, nbpath)
