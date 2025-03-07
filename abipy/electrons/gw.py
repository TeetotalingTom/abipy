# coding: utf-8
"""Classes for the analysis of GW calculations."""
from __future__ import annotations

import sys
import copy
import numpy as np
import pandas as pd

from collections import namedtuple, OrderedDict
from io import StringIO
from tabulate import tabulate
from monty.string import list_strings, is_string, marquee
from monty.collections import dict2namedtuple
from monty.functools import lazy_property
from monty.termcolor import cprint
from monty.bisect import find_le, find_ge
from abipy.core.func1d import Function1D
from abipy.core.kpoints import Kpoint, KpointList, Kpath, IrredZone, has_timrev_from_kptopt
from abipy.core.mixins import AbinitNcFile, Has_Structure, Has_ElectronBands, NotebookWriter
from abipy.core.structure import Structure
from abipy.iotools import ETSF_Reader
from abipy.tools.plotting import (ArrayPlotter, add_fig_kwargs, get_ax_fig_plt, get_axarray_fig_plt, Marker,
    set_axlims, set_visible, rotate_ticklabels, set_ax_xylabels, set_grid_legend)
from abipy.tools.typing import Figure, KptSelect
from abipy.tools import duck
from abipy.abio.robots import Robot
from abipy.electrons.ebands import ElectronBands, RobotWithEbands
from abipy.electrons.scissors import Scissors


__all__ = [
    "QPState",
    "SigresFile",
    "SigresRobot",
]


class QPState(namedtuple("QPState", "spin kpoint band e0 qpe qpe_diago vxcme sigxme sigcmee0 vUme ze0")):
    """
    Quasi-particle result for given (spin, kpoint, band).

    .. Attributes:

        spin: spin index (C convention, i.e >= 0)
        kpoint: |Kpoint| object.
        band: band index. (C convention, i.e >= 0).
        e0: Initial KS energy.
        qpe: Quasiparticle energy (complex) computed with the perturbative approach.
        qpe_diago: Quasiparticle energy (real) computed by diagonalizing the self-energy.
        vxcme: Matrix element of vxc[n_val] with nval the valence charge density.
        sigxme: Matrix element of Sigma_x.
        sigcmee0: Matrix element of Sigma_c(e0) with e0 being the KS energy.
        vUme: Matrix element of the vU term of the LDA+U Hamiltonian.
        ze0: Renormalization factor computed at e=e0.

    .. note::

        Energies are in eV.
    """
    @property
    def qpeme0(self) -> complex:
        """E_QP - E_0 in eV"""
        return self.qpe - self.e0

    @property
    def re_qpe(self) -> float:
        """Real part of the QP energy."""
        return self.qpe.real

    @property
    def imag_qpe(self) -> float:
        """Imaginay part of the QP energy."""
        return self.qpe.imag

    @property
    def skb(self) -> tuple:
        """Tuple with (spin, kpoint, band)"""
        return self.spin, self.kpoint, self.band

    def copy(self) -> QPState:
        """Return shallow copy."""
        d = {f: copy.copy(getattr(self, f)) for f in self._fields}
        return self.__class__(**d)

    @classmethod
    def get_fields(cls, exclude=()) -> tuple:
        fields = list(cls._fields) + ["qpeme0"]
        for e in exclude:
            fields.remove(e)
        return tuple(fields)

    def as_dict(self, **kwargs) -> dict:
        """
        Convert self into a dictionary.
        """
        od = OrderedDict(zip(self._fields, self))
        od["qpeme0"] = self.qpeme0
        return od

    def to_strdict(self, fmt=None) -> dict:
        """
        Ordered dictionary mapping fields --> strings.
        """
        d = self.as_dict()
        for k, v in d.items():
            if duck.is_intlike(v):
                d[k] = "%d" % int(v)
            elif isinstance(v, Kpoint):
                d[k] = "%s" % v
            elif np.iscomplexobj(v):
                if abs(v.imag) < 1.e-3:
                    d[k] = "%.2f" % v.real
                else:
                    d[k] = "%.2f%+.2fj" % (v.real, v.imag)
            else:
                try:
                    d[k] = "%.2f" % v
                except TypeError as exc:
                    #print("k", k, str(exc))
                    d[k] = str(v)
        return d

    @property
    def tips(self) -> str:
        """Bound method of self that returns a dictionary with the description of the fields."""
        return self.__class__.TIPS()

    @classmethod
    def TIPS(cls) -> str:
        """
        Class method that returns a dictionary with the description of the fields.
        The string are extracted from the class doc string.
        """
        try:
            return cls._TIPS

        except AttributeError:
            # Parse the doc string.
            cls._TIPS = _TIPS = {}
            lines = cls.__doc__.splitlines()

            for i, line in enumerate(lines):
                if line.strip().startswith(".. Attributes"):
                    lines = lines[i+1:]
                    break

            def num_leadblanks(string):
                """Returns the number of the leading whitespaces."""
                return len(string) - len(string.lstrip())

            for field in cls._fields:
                for i, line in enumerate(lines):

                    if line.strip().startswith(field + ":"):
                        nblanks = num_leadblanks(line)
                        desc = []
                        for s in lines[i+1:]:
                            if nblanks == num_leadblanks(s) or not s.strip():
                                break
                            desc.append(s.lstrip())

                        _TIPS[field] = "\n".join(desc)

            diffset = set(cls._fields) - set(_TIPS.keys())
            if diffset:
                raise RuntimeError("The following fields are not documented: %s" % str(diffset))

            return _TIPS

    @classmethod
    def get_fields_for_plot(cls, with_fields, exclude_fields) -> list:
        """
        Return list of QPState fields to plot from input arguments.
        """
        all_fields = list(cls.get_fields(exclude=["spin", "kpoint"]))[:]

        # Initialize fields.
        if is_string(with_fields) and with_fields == "all":
            fields = all_fields
        else:
            fields = list_strings(with_fields)
            for f in fields:
                if f not in all_fields:
                    raise ValueError("Field %s not in allowed values %s" % (f, all_fields))

        # Remove entries
        if exclude_fields:
            if is_string(exclude_fields):
                exclude_fields = exclude_fields.split()
            for e in exclude_fields:
                try:
                    fields.remove(e)
                except ValueError:
                    pass

        return fields


class QPList(list):
    """
    A list of quasiparticle corrections for a given spin.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.is_e0sorted = kwargs.get("is_e0sorted", False)

    def __repr__(self) -> str:
        return "<%s at %s, len=%d>" % (self.__class__.__name__, id(self), len(self))

    def __str__(self) -> str:
        """String representation."""
        return self.to_string()

    def to_table(self) -> list[list[str]]:
        """Return a table (list of list of strings)."""
        header = QPState.get_fields(exclude=["spin", "kpoint"])
        table = [header]
        for qp in self:
            d = qp.to_strdict(fmt=None)
            table.append([d[k] for k in header])

        return tabulate(table, tablefmt="plain")

    def to_string(self, verbose: int = 0) -> str:
        """String representation."""
        return self.to_table()

    def copy(self) -> QPList:
        """Copy of self."""
        return self.__class__([qp.copy() for qp in self], is_e0sorted=self.is_e0sorted)

    def sort_by_e0(self) -> QPList:
        """Return a new object with the E0 energies sorted in ascending order."""
        return self.__class__(sorted(self, key=lambda qp: qp.e0), is_e0sorted=True)

    def get_e0mesh(self) -> np.ndarray:
        """Return the E0 energies."""
        if not self.is_e0sorted:
            raise ValueError("QPState corrections are not sorted. Use sort_by_e0.")

        return np.array([qp.e0 for qp in self])

    def get_field(self, field) -> np.ndarray:
        """|numpy-array| containing the values of field."""
        return np.array([getattr(qp, field) for qp in self])

    def get_skb_field(self, skb, field):
        """Return the value of field for the given spin kp band tuple, None if not found"""
        for qp in self:
            if qp.skb == skb:
                return getattr(qp, field)
        return None

    def get_qpenes(self) -> np.ndarray:
        """Return an array with the :class:`QPState` energies."""
        return self.get_field("qpe")

    def get_qpeme0(self) -> np.ndarray:
        """Return an arrays with the :class:`QPState` corrections."""
        return self.get_field("qpeme0")

    def merge(self, other, copy=False) -> QPList:
        """
        Merge self with other. Return new :class:`QPList` object

        Raise:
            `ValueError` if merge cannot be done.
        """
        skb0_list = [qp.skb for qp in self]
        for qp in other:
            if qp.skb in skb0_list:
                raise ValueError("Found duplicated (s,b,k) indexes: %s" % str(qp.skb))

        qps = self.copy() + other.copy() if copy else self + other
        return self.__class__(qps)

    @add_fig_kwargs
    def plot_qps_vs_e0(self, with_fields="all", exclude_fields=None, fermie=None,
                       ax_list=None, sharey=False, xlims=None, fontsize=12, **kwargs) -> Figure:
        """
        Plot the QP results as function of the initial KS energy.

        Args:
            with_fields: The names of the qp attributes to plot as function of e0.
                Accepts: List of strings or string with tokens separated by blanks.
                See :class:`QPState` for the list of available fields.
            exclude_fields: Similar to ``with_field`` but excludes fields.
            fermie: Value of the Fermi level used in plot. None for absolute e0s.
            ax_list: List of |matplotlib-Axes| for plot. If None, new figure is produced.
            sharey: True if y-axis should be shared.
            kwargs: linestyle, color, label, marker

        Returns: |matplotlib-Figure|
        """
        fields = QPState.get_fields_for_plot(with_fields, exclude_fields)
        if not fields: return None

        num_plots, ncols, nrows = len(fields), 1, 1
        if num_plots > 1:
            ncols = 2
            nrows = (num_plots // ncols) + (num_plots % ncols)

        # Build grid of plots.
        ax_list, fig, plt = get_axarray_fig_plt(ax_list, nrows=nrows, ncols=ncols,
                                                sharex=True, sharey=sharey, squeeze=False)
        ax_list = np.array(ax_list).ravel()

        # Get qplist and sort it.
        qps = self if self.is_e0sorted else self.sort_by_e0()
        e0mesh = qps.get_e0mesh()
        xlabel = r"$\epsilon_{KS}\;(eV)$"
        #print("fermie", fermie)
        if fermie is not None:
            xlabel = r"$\epsilon_{KS}-\epsilon_F\;(eV)$"
            e0mesh -= fermie

        kw_linestyle = kwargs.pop("linestyle", "o")
        if "marker" in kwargs:
            kw_linestyle = ""

        kw_color = kwargs.pop("color", None)
        kw_label = kwargs.pop("label", None)

        for ii, (field, ax) in enumerate(zip(fields, ax_list)):
            irow, icol = divmod(ii, ncols)
            ax.grid(True)
            if irow == nrows - 1:
                ax.set_xlabel(xlabel)
            ax.set_ylabel(field, fontsize=fontsize)
            yy = qps.get_field(field)

            # TODO real and imag?
            #print("kwargs:", kwargs)
            #print("field:", field, e0mesh.shape, yy.real.shape)
            #ax.plot(e0mesh, yy.real, kw_linestyle, color=kw_color, label=kw_label, **kwargs)
            ax.scatter(e0mesh, yy.real, color=kw_color, label=kw_label, **kwargs)
            set_axlims(ax, xlims, "x")

        if kw_label:
            ax_list[0].legend(loc="best", fontsize=fontsize, shadow=True)

        # Get around a bug in matplotlib
        if num_plots % ncols != 0: ax_list[-1].axis('off')

        return fig

    def build_scissors(self, domains, bounds=None, k=3, plot=False, **kwargs):
        """
        Construct a scissors operator by interpolating the corrections
        as function of the initial KS energies e0.

        Args:
            domains: list in the form [ [start1, stop1], [start2, stop2]
                Domains should not overlap, cover e0mesh, and given in increasing order.
                Holes are permitted but the interpolation will raise an exception if
                the point is not in domains.
            bounds: Specify how to handle out-of-boundary conditions, i.e. how to treat
                energies that do not fall inside one of the domains (not used at present)
            plot: If true, use matplolib plot to compare input data  and fit.

        Return:
            instance of :class:`Scissors`operator

        Usage example:

        .. code-block:: python

            # Build the scissors operator.
            scissors = qplist_spin[0].build_scissors(domains)

            # Compute list of interpolated QP energies.
            qp_enes = [scissors.apply(e0) for e0 in ks_energies]
        """
        # Sort QP corrections according to the initial KS energy.
        qps = self.sort_by_e0()
        e0mesh, qpcorrs = qps.get_e0mesh(), qps.get_qpeme0()

        # Check domains.
        domains = np.atleast_2d(domains)
        dsize, dflat = domains.size, domains.ravel()

        for idx, v in enumerate(dflat):
            if idx == 0 and v > e0mesh[0]:
                raise ValueError("min(e0mesh) %s is not included in domains" % e0mesh[0])
            if idx == dsize-1 and v < e0mesh[-1]:
                raise ValueError("max(e0mesh) %s is not included in domains" % e0mesh[-1])
            if idx != dsize-1 and dflat[idx] > dflat[idx+1]:
                raise ValueError("domain boundaries should be given in increasing order.")
            if idx == dsize-1 and dflat[idx] < dflat[idx-1]:
                raise ValueError("domain boundaries should be given in increasing order.")

        # Create the sub_domains and the spline functions in each subdomain.
        func_list, residues = [], []

        if len(domains) == 2:
            #print('forcing extremal point on the scissor')
            ndom = 0
        else:
            ndom = 99

        for dom in domains[:]:
            ndom += 1
            low, high = dom[0], dom[1]
            start, stop = find_ge(e0mesh, low), find_le(e0mesh, high)

            dom_e0 = e0mesh[start:stop+1]
            dom_corr = qpcorrs[start:stop+1]

            # todo check if the number of non degenerate data points > k
            from scipy.interpolate import UnivariateSpline
            w = len(dom_e0)*[1]
            if ndom == 1:
                w[-1] = 1000
            elif ndom == 2:
                w[0] = 1000
            else:
                w = None
            f = UnivariateSpline(dom_e0, dom_corr, w=w, bbox=[None, None], k=k, s=None)
            func_list.append(f)
            residues.append(f.get_residual())

        # Build the scissors operator.
        sciss = Scissors(func_list, domains, residues, bounds)

        # Compare fit with input data.
        if plot:
            title = kwargs.pop("title", None)
            import matplotlib.pyplot as plt
            plt.plot(e0mesh, qpcorrs, 'o', label="input data")
            if title: plt.suptitle(title)
            for dom in domains[:]:
                plt.plot(2*[dom[0]], [min(qpcorrs), max(qpcorrs)])
                plt.plot(2*[dom[1]], [min(qpcorrs), max(qpcorrs)])
            intp_qpc = [sciss.apply(e0) for e0 in e0mesh]
            plt.plot(e0mesh, intp_qpc, label="scissor")
            plt.legend(bbox_to_anchor=(0.9, 0.2))
            plt.show()

        return sciss


class SelfEnergy:
    """
    This object stores the e-e self-energy along the real-axis frequency domain with
    the associated spectral function A(w) and, optionally, the values along the imaginary axis.
    All energies are in eV.
    """

    # Latex symbols used in matplotlib plots.
    latex_symbols = dict(
        re=r"$\Re{\Sigma_{nk}(\omega)}$",
        im=r"$\Im{\Sigma_{nk}(\omega)}$",
        aw=r"$A_{nk}(\omega)}$",
    )

    def __init__(self,
                 spin: int,
                 kpoint: KptSelect,
                 band: int,
                 wmesh: np.ndarray,
                 xc_vals: np.ndarray,
                 x_val: float,
                 ze0: complex,
                 aw_vals: np.ndarray,
                 iw_mesh: np.ndarray | None = None,
                 c_iw_values: np.ndarray | None = None,
                 tau_mp_mesh: np.ndarray | None = None,
                 c_tau_mp_values: np.ndarray | None = None):
        """
        Args:
            spin: Spin index
            kpoint: K-point in self-energy. Accepts |Kpoint|, vector or index.
            band: band index
            wmesh: Frequency mesh along the real-axis in eV
            xc_vals: Matrix elements of sigma_xc on wmesh.
            x_val: Matrix element of sigma_x.
            ze0: Renormalization factor at the bare energy.
            aw_vals: Spectral function A(w) on wmesh
            iw_mesh: Frequency mesh along the imag axis in eV. Optional
            c_iw_values: Values of Sigma_c(iw) on iw_mesh. Optional
            tau_mp_mesh: Mesh for imaginary time in a.u. (negative and positive values)
            c_tau_mp_values: Values of Sigma_c(i tau) (negative and positive values)
        """
        self.spin, self.kpoint, self.band = spin, kpoint, band

        self.wmesh = np.array(wmesh)
        self.xc = Function1D(self.wmesh, xc_vals)
        self.x_val = x_val
        self.ze0 = ze0
        self.aw = Function1D(self.wmesh, aw_vals)
        if len(xc_vals) != len(aw_vals):
            raise ValueError(f"{len(xc_vals)=} != {len(aw_vals)=}")

        # Optionally, store Sigma(iw)
        self.c_iw= None
        if iw_mesh is not None and c_iw_values is not None:
            self.c_iw = Function1D(iw_mesh, c_iw_values)

        # Optionally, store Sigma(itau) for positive and negative imaginary times.
        self.c_tau = None
        if tau_mp_mesh is not None and c_tau_mp_values is not None:
            self.c_tau = Function1D(tau_mp_mesh, c_tau_mp_values)

    @property
    def has_c_iw(self) -> bool:
        """True if Sigma_c(i w) is available."""
        return self.c_iw is not None

    @property
    def has_c_tau(self) -> bool:
        """True if Sigma_c(i tau) is available."""
        return self.c_tau is not None

    def __str__(self) -> str:
        return self.to_string()

    def to_string(self, verbose: int=0, title=None) -> str:
        """
        String representation with verbosity level `verbose`.
        """
        lines = []; app = lines.append
        if title is not None: app(marquee(title, mark="="))
        app("K-point: %s, band: %d, spin: %d" % (repr(self.kpoint), self.band, self.spin))
        app("Number of real frequencies: %d, from %.1f to %.1f (eV)" % (len(self.wmesh), self.wmesh[0], self.wmesh[-1]))
        if self.has_c_iw:
            iw_mesh = self.c_iw.mesh
            app("Number of imaginary frequencies: %d, from %.1f to %.1f (eV)" % (
                len(iw_mesh), iw_mesh[0], iw_mesh[-1]))
        if self.has_c_tau:
            tau_mesh = self.c_tau.mesh
            app("Number of imaginary times: %d, from %.1f to %.1f (a.u.)" % (
                len(tau_mesh), tau_mesh[0], tau_mesh[-1]))

        return "\n".join(lines)

    def _get_ys(self, what: str) -> dict:
        """Return the name of the array to plot from what."""
        return dict(
            re=self.xc.values.real,
            im=self.xc.values.imag,
            aw=self.aw.values,
        )[what]

    def plot_ax(self, ax, what="a", fontsize=8, **kwargs) -> list:
        """
        Helper function to plot data on the axis ax.

        Args:
            ax: |matplotlib-Axes| or None if a new figure should be created.
            what: "a" for spectral function,
                  "s" for self-energy i.e. Re/Im on the same ax.
                  "sre" for Re(Sigma) only.
                  "sim" for Im(Sigma) only.
            fontsize: legend and title fontsize.

        Return: List of matplotlib lines.
        """
        lines = []
        extend = lines.extend

        if what in {"s", "sre", "sim"}:
            f = self.xc
            label = kwargs.get("label", r"$\Sigma(\omega)$")
            if what in {"s", "sre"}:
                extend(f.plot_ax(ax, cplx_mode="re", label="Re " + label))
            if what in {"s", "sim"}:
                extend(f.plot_ax(ax, cplx_mode="im", label="Im " + label))

        elif what == "a":
            label = kwargs.get("label", r"$A(\omega)$")
            extend(self.aw.plot_ax(ax, label=label))

        else:
            raise ValueError(f"Don't know how to handle {what=}")

        #ax.set_ylabel('Energy (eV)')
        ax.grid(True)
        ax.legend(loc="best", fontsize=fontsize, shadow=True)

        return lines

    @add_fig_kwargs
    def plot(self,
             ax_list=None,
             what_list=("re", "im", "aw"),
             fermie=None,
             xlims=None,
             fontsize=8,
             **kwargs) -> Figure:
        """
        Plot the real/imaginary part of the self-energy as well as the spectral function.
        along the real frequency axis.

        Args:
            ax_list: List of |matplotlib-Axes| for plot. If None, new figure is produced.
            what_list: List of strings selecting the quantity to plot.
            fermie: Value of the Fermi level used in plot. None for absolute energies
            xlims: Set the data limits for the x-axis. Accept tuple e.g. ``(left, right)``
                or scalar e.g. ``left``. If left (right) is None, default values are used.
            fontsize: legend and label fontsize.
            kwargs: Keyword arguments passed to ax.plot

        Returns: |matplotlib-Figure|
        """
        what_list = list_strings(what_list)
        ax_list, fig, plt = get_axarray_fig_plt(ax_list, nrows=len(what_list), ncols=1,
                                                sharex=True, sharey=False, squeeze=False)
        ax_list = np.array(ax_list).ravel()
        xlabel = r"$\omega\;(eV)$"
        wmesh = self.wmesh
        if fermie is not None:
            xlabel = r"$\omega - \epsilon_F}\;(eV)$"
            wmesh = self.wmesh - fermie

        kw_color = kwargs.pop("color", None)
        kw_label = kwargs.pop("label", None)
        for i, (what, ax) in enumerate(zip(what_list, ax_list)):
            ax.grid(True)
            ax.set_ylabel(self.latex_symbols[what])
            if (i == len(ax_list) - 1): ax.set_xlabel(xlabel)
            ax.plot(wmesh, self._get_ys(what), color=kw_color, label=kw_label if i == 0 else None)
            set_axlims(ax, xlims, "x")
            if i == 0 and kw_label:
                ax.legend(loc="best", shadow=True, fontsize=fontsize)

        if "title" not in kwargs:
            title = "k-point: %s, band: %d, spin: %d" % (repr(self.kpoint), self.band, self.spin)
            fig.suptitle(title, fontsize=fontsize)

        return fig

    def plot_reima_rw(self, ax_list: list, with_xlabels: bool = False, **kwargs) -> list:
        """
        Plot Re/Im (Sigma(w)) and the spectral function A(w) on `ax_list` with w on the real-axis.

        Return: list of matplotlib lines.
        """
        if len(ax_list) != 3:
            raise ValueError(f"Expecting ax_list of len = 3, got: {len(ax_list)}")

        xlabel = r"$\omega$ (eV)" if with_xlabels else ""

        # Plot Sigma(w) along the real axis.
        l0 = self.xc.plot_ax(ax_list[0], cplx_mode="re", **kwargs)
        set_ax_xylabels(ax_list[0], xlabel, r"$\Re{\Sigma}(\omega)$ (eV)")
        l1 = self.xc.plot_ax(ax_list[1], cplx_mode="im", **kwargs)
        set_ax_xylabels(ax_list[1], xlabel, r"$\Im{\Sigma}(\omega)$ (eV)")

        # Plot A(w)
        l2 = self.aw.plot_ax(ax_list[2], **kwargs)
        set_ax_xylabels(ax_list[2], r"$\omega$ (eV)", r"$A(\omega)$ (1/eV)")

        return [l0, l1, l2]

    def plot_reimc_iw(self, ax_list: list, with_xlabels: bool = False, **kwargs) -> list:
        """
        Plot Re/Im (Sigma_c(iw)) of the correlated part on the imaginary-axis on `ax_list`.

        Return: list of matplotlib lines.
        """
        if len(ax_list) != 2:
            raise ValueError(f"Expecting ax_list of len = 2, got: {len(ax_list)}")

        xlabel = r"$i\omega$ (eV)" if with_xlabels else ""

        l0 = self.c_iw.plot_ax(ax_list[0], cplx_mode="re", **kwargs)
        set_ax_xylabels(ax_list[0], xlabel, r"$\Re{\Sigma_c}(i\omega)$ (eV)")
        self.c_iw.plot_ax(ax_list[1], cplx_mode="im", **kwargs)
        l1 = set_ax_xylabels(ax_list[1], r"$i\omega$ (eV)", r"$\Im{\Sigma_c}(i\omega)$ (eV)")

        return [l0, l1]

    def plot_reimc_tau(self, ax_list: list, with_xlabels: bool = False, **kwargs) -> list:
        """
        Plot Re/Im (Sigma_c(i tau)) of the correlated part on the imaginary-axis on `ax_list`.

        Return: list of matplotlib lines.
        """
        if len(ax_list) != 2:
            raise ValueError(f"Expecting ax_list of len = 2, got: {len(ax_list)}")

        xlabel = r"$i\tau$ (a.u.)" if with_xlabels else ""

        l0 = self.c_tau.plot_ax(ax_list[0], cplx_mode="re", **kwargs)
        set_ax_xylabels(ax_list[0], xlabel, r"$\Re{\Sigma_c}(i\tau)$ (eV)")
        self.c_tau.plot_ax(ax_list[1], cplx_mode="im", **kwargs)
        l1 = set_ax_xylabels(ax_list[1], r"$i\tau$ (a.u.)", r"$\Im{\Sigma_c}(i\tau)$ (eV)")

        return [l0, l1]

    #@add_fig_kwargs
    #def plot_with_other(self, other: SelfEnergy, **kwargs) -> Figure:
    #    """
    #    """
    #    what_list = ["re", "im", "aw"]
    #    ax_list, fig, plt = get_axarray_fig_plt(ax_list, nrows=len(what_list), ncols=1,
    #                                            sharex=True, sharey=False, squeeze=False)
    #    ax_list = np.array(ax_list).ravel()

    #    #for i, (what, ax) in enumerate(zip(what_list, ax_list)):
    #    return fig



class SigresFile(AbinitNcFile, Has_Structure, Has_ElectronBands, NotebookWriter):
    """
    Container storing the GW results reported in the SIGRES.nc file.

    Usage example:

    .. code-block:: python

        sigres = SigresFile("foo_SIGRES.nc")
        sigres.plot_qps_vs_e0()

    .. rubric:: Inheritance Diagram
    .. inheritance-diagram:: SigresFile
    """
    # Markers used for up/down bands.
    marker_spin = {0: "^", 1: "v"}

    color_spin = {0: "k", 1: "r"}

    @classmethod
    def from_file(cls, filepath: str) -> SigresFile:
        """Initialize an instance from file."""
        return cls(filepath)

    def __init__(self, filepath: str):
        """Read data from the netcdf file path."""
        super().__init__(filepath)

        # Keep a reference to the SigresReader.
        self.reader = self.r = reader = SigresReader(self.filepath)

        self._structure = reader.read_structure()
        self.gwcalctyp = reader.gwcalctyp
        self.ibz = reader.ibz
        #self.sigma_kpoints = reader.sigma_kpoints
        self.nkcalc = len(self.sigma_kpoints)

        self.bstart_sk = reader.bstart_sk
        self.bstop_sk = reader.bstop_sk

        self.min_bstart = reader.min_bstart
        self.max_bstart = reader.max_bstart
        self.min_bstop = reader.min_bstop
        self.max_bstop = reader.max_bstop

        self._ebands = ebands = reader.ks_bands

        qplist_spin = self.qplist_spin

        # TODO handle the case in which nkptgw < nkibz
        self.qpgaps = reader.read_qpgaps()
        self.qpenes = reader.read_qpenes()
        self.ksgaps = reader.read_ksgaps()

    @property
    def sigma_kpoints(self):
        """The k-points where QP corrections have been calculated."""
        return self.r.sigma_kpoints

    def get_marker(self, qpattr):
        """
        Return :class:`Marker` object associated to the QP attribute qpattr.
        Used to prepare plots of KS bands with markers.
        """
        # Each marker is a list of tuple(x, y, value)
        x, y, s = [], [], []

        for spin in range(self.nsppol):
            for qp in self.qplist_spin[spin]:
                ik = self.ebands.kpoints.index(qp.kpoint)
                x.append(ik)
                y.append(qp.e0)
                size = getattr(qp, qpattr)
                # Handle complex quantities
                if np.iscomplex(size): size = size.real
                s.append(size)

        return Marker(*(x, y, s))

    @lazy_property
    def params(self) -> dict:
        """
        dictionary with parameters that might be subject to convergence studies e.g ecuteps
        """
        od = self.get_ebands_params()
        od.update(self.r.read_params())
        return od

    def close(self) -> None:
        """Close the netcdf file."""
        self.r.close()

    def __str__(self) -> str:
        return self.to_string()

    def to_string(self, verbose: int = 0) -> str:
        """
        String representation with verbosity level ``verbose``.
        """
        lines = []; app = lines.append

        app(marquee("File Info", mark="="))
        app(self.filestat(as_string=True))
        app("")
        app(self.structure.to_string(verbose=verbose, title="Structure"))
        app("")
        app(self.ebands.to_string(title="Kohn-Sham bands", with_structure=False))
        app("")

        # GW Section.
        # TODO: Finalize the implementation: add GW metadata.
        app(marquee("QP direct gaps", mark="="))
        for kcalc in self.sigma_kpoints:
            for spin in range(self.nsppol):
                qp_dirgap = self.get_qpgap(spin, kcalc)
                app("QP_dirgap: %.3f (eV) for k-point: %s, spin: %s" % (qp_dirgap, repr(kcalc), spin))
                #ks_dirgap =
        app("")

        # Show QP results
        strio = StringIO()
        self.print_qps(precision=3, ignore_imag=verbose == 0, file=strio)
        strio.seek(0)
        app("")
        app(marquee("QP results for each k-point and spin (all in eV)", mark="="))
        app("".join(strio))
        app("")

        return "\n".join(lines)

    @property
    def structure(self) -> Structure:
        """|Structure| object."""
        return self._structure

    @property
    def ebands(self) -> ElectronBands:
        """|ElectronBands| with the KS energies."""
        return self._ebands

    @property
    def has_spectral_function(self) -> bool:
        """True if sigres file contains the spectral function."""
        return self.r.has_spfunc

    @lazy_property
    def qplist_spin(self) -> tuple:
        """Tuple of :class:`QPList` objects indexed by spin."""
        return self.r.read_allqps()

    def get_qplist(self, spin: int, kpoint: KptSelect, ignore_imag: bool = False) -> QPList:
        """Return :class`QPList` for the given (spin, kpoint)"""
        return self.r.read_qplist_sk(spin, kpoint, ignore_imag=ignore_imag)

    def get_qpcorr(self, spin: int, kpoint: KptSelect, band: int, ignore_imag: bool = False) -> QPState:
        """Returns the :class:`QPState` object for the given (s, k, b)"""
        return self.r.read_qp(spin, kpoint, band, ignore_imag=ignore_imag)

    @lazy_property
    def qpgaps(self) -> np.ndarray:
        """|numpy-array| of shape [nsppol, nkibz] with the QP direct gaps in eV."""
        return self.r.read_qpgaps()

    def get_qpgap(self, spin: int, kpoint: KptSelect, with_ksgap: bool = False):
        """
        Return the QP gap in eV at the given (spin, kpoint)
        """
        ik = self.r.kpt2ibz(kpoint)
        if not with_ksgap:
            return self.qpgaps[spin, ik]
        else:
            return self.qpgaps[spin, ik], self.ksgaps[spin, ik]

    def read_sigee_skb(self, spin: int, kpoint: KptSelect, band: int) -> SelfEnergy:
        """"
        Read self-energy for (spin, kpoint, band).
        """
        ik_ibz = self.r.kpt2ibz(kpoint)
        kpoint = self.ibz[ik_ibz]
        wmesh, xc_vals = self.r.read_sigmaw(spin, ik_ibz, band)

        aw_vals = None
        if self.r.has_spfunc:
            _, aw_vals = self.r.read_spfunc(spin, ik_ibz, band)

        # Values along the imag axis are available only if AC has been used.
        iw_mesh, c_iw_values = None, None
        ib_gw = band - self.min_bstart
        if self.r.nomega_i > 0:
            # Read Sigma_c(iw) if available.
            # sigcmesi(b1gw:b2gw, nkibz, nomega_i, nsppol*nsig_ab))
            iw_mesh = self.r.read_value("omega_i")[:, 1]
            var = self.r.read_variable("sigcmesi")
            c_iw_values = var[spin, :, ik_ibz, ib_gw, 0] + 1j*var[spin, :, ik_ibz, ib_gw, 1]

        # nctkarr_t('sigxme', "dp", 'nbgw, number_of_kpoints, ndim_sig')
        x_val = self.r._sigxme[spin, ik_ibz, ib_gw]
        # nctkarr_t('ze0',"dp", 'cplex, nbgw, number_of_kpoints, number_of_spins')
        ze0 =  self.r.read_variable("ze0")[spin, ik_ibz, ib_gw]
        ze0 = ze0[0] + 1j*ze0[1]

        return SelfEnergy(spin, kpoint, band, wmesh, xc_vals, x_val, ze0, aw_vals,
                          iw_mesh=iw_mesh, c_iw_values=c_iw_values)

    def print_qps(self, precision=3, ignore_imag=True, file=sys.stdout) -> None:
        """
        Print QP results to stream ``file``.

        Args:
            precision: Number of significant digits.
            ignore_imag: True if imaginary part should be ignored.
            file: Output stream.
        """
        from abipy.tools.printing import print_dataframe
        keys = "band e0 qpe qpe_diago vxcme sigxme sigcmee0 vUme ze0".split()
        for kcalc in self.sigma_kpoints:
            for spin in range(self.nsppol):
                df_sk = self.get_dataframe_sk(spin, kcalc, ignore_imag=ignore_imag)[keys]
                print_dataframe(df_sk, title="K-point: %s, spin: %s" % (repr(kcalc), spin),
                                precision=precision, file=file)

    def get_points_from_ebands(self, ebands_kpath, dist_tol=1e-12, size=24, verbose=0) -> Marker:
        """
        Generate Marker object storing the QP energies lying on the k-path used by ebands_kpath.
        Mainly used to plot the QP energies in ebands.plot when the QP energies
        are interpolated with the SKW method.

        Args:
            ebands_kpath: |ElectronBands| object with the QP energies along an arbitrary k-path.
            dist_tol: A point is considered to be on the path if its distance from the line
                is less than dist_tol.
            size: The marker size in points**2
            verbose: Verbosity level

        Example::

            r = sigres.interpolate(lpratio=5,
                                   ks_ebands_kpath=ks_ebands_kpath,
                                   ks_ebands_kmesh=ks_ebands_kmesh
                                   )
            points = sigres.get_points_from_ebands(r.qp_ebands_kpath, size=24)
            r.qp_ebands_kpath.plot(points=points)
        """
        kpath = ebands_kpath.kpoints
        if not ebands_kpath.kpoints.is_path:
            raise TypeError("Expecting band structure with a Kpath, got %s" % type(kpath))
        if verbose:
            print("Input kpath\n", ebands_kpath.kpoints)
            print("sigma_kpoints included in GW calculation\n", self.sigma_kpoints)
            print("lines\n", kpath.lines)
            print("kpath.frac_bounds:\n", kpath.frac_bounds)
            print("kpath.cart_bounds:\n", kpath.frac_bounds)

        # Construct the stars of the k-points for all k-points included in the GW calculation.
        # In principle, the input k-path is arbitrary and not necessarily in the IBZ used for GW
        # so we have to build the k-stars and find the k-points lying along the path and keep
        # track of the mapping kpt --> star --> kcalc
        gw_stars = [kpoint.compute_star(self.structure.abi_spacegroup.fm_symmops) for kpoint in self.sigma_kpoints]
        cart_coords, back2istar = [], []
        for istar, gw_star in enumerate(gw_stars):
            cart_coords.extend([k.cart_coords for k in gw_star])
            back2istar.extend([istar] * len(gw_star))
        cart_coords = np.reshape(cart_coords, (-1, 3))

        # Find (star) k-points on the path.
        p = kpath.find_points_along_path(cart_coords, dist_tol=dist_tol)
        if len(p.ikfound) == 0:
            cprint("Warning: Found zero points lying on the input k-path. Try to increase dist_tol.", "yellow")
            return Marker()

        # Read complex GW energies from file.
        qp_arr = self.r.read_value("egw", cmode="c")

        # Each marker is a list of tuple(x, y, value)
        x, y, s = [], [], []
        kpath_lenght = kpath.ds.sum()

        for ik, dalong_path in zip(p.ikfound, p.dist_list):
            istar = back2istar[ik]
            # The k-point used in the GW calculation.
            gwk = gw_stars[istar].base_point
            # Indices needed to access SIGRES arrays (we have to live with this format)
            ik_ibz = self.r.kpt2ibz(gwk)
            ik_b = self.r.kpt2ikcalc(gwk)
            for spin in range(self.nsppol):
                # Need to select bands included in the GW calculation.
                for qpe in qp_arr[spin, ik_ibz, self.bstart_sk[spin, ik_b]:self.bstop_sk[spin, ik_b]]:
                    # Assume the path is properly normalized.
                    x.append((dalong_path / kpath_lenght) * (len(kpath) - 1))
                    y.append(qpe.real)
                    s.append(size)

        return Marker(*(x, y, s))

    @add_fig_kwargs
    def plot_qpgaps(self, ax=None, plot_qpmks=True, fontsize=8, **kwargs) -> Figure:
        """
        Plot the KS and the QP direct gaps for all the k-points and spins available on file.

        Args:
            ax: |matplotlib-Axes| or None if a new figure should be created.
            plot_qpmks: If False, plot QP_gap, KS_gap else (QP_gap - KS_gap)
            fontsize: legend and title fontsize.
            kwargs: Passed to ax.plot method except for marker.

        Returns: |matplotlib-Figure|
        """
        ax, fig, plt = get_ax_fig_plt(ax=ax)
        label = kwargs.pop("label", None)
        xs = np.arange(self.nkcalc)

        # Add xticklabels from k-points.
        tick_labels = [repr(k) for k in self.sigma_kpoints]
        ax.set_xticks(xs)
        ax.set_xticklabels(tick_labels, fontdict=None, rotation=30, minor=False, size="x-small")

        for spin in range(self.nsppol):
            qp_gaps, ks_gaps = map(np.array, zip(*[self.get_qpgap(spin, kcalc, with_ksgap=True)
                                   for kcalc in self.sigma_kpoints]))
            if not plot_qpmks:
                # Plot QP gaps
                ax.plot(xs, qp_gaps, marker=self.marker_spin[spin],
                        label=label if spin == 0 else None, **kwargs)
                # Add KS gaps
                #ax.scatter(xx, ks_gaps) #, label="KS gap %s" % label)
            else:
                # Plot QP_gap - KS_gap
                ax.plot(xs, qp_gaps - ks_gaps, marker=self.marker_spin[spin],
                    label=label if spin == 0 else None, **kwargs)

            ax.grid(True)
            ax.set_xlabel("K-point")
            if plot_qpmks:
                ax.set_ylabel("QP-KS gap (eV)")
            else:
                ax.set_ylabel("QP direct gap (eV)")
            #ax.set_title("k:%s" % (repr(kcalc)), fontsize=fontsize)
            if label:
                ax.legend(loc="best", fontsize=fontsize, shadow=True)

        return fig

    @add_fig_kwargs
    def plot_qps_vs_e0(self, with_fields="all", exclude_fields=None, e0="fermie",
                       xlims=None, sharey=False, ax_list=None, fontsize=8, **kwargs) -> Figure:
        """
        Plot QP result in the SIGRES file as function of the KS energy.

        Args:
            with_fields: The names of the qp attributes to plot as function of eKS.
                Accepts: List of strings or string with tokens separated by blanks.
                See :class:`QPState` for the list of available fields.
            exclude_fields: Similar to ``with_fields`` but excludes fields
            e0: Option used to define the zero of energy in the band structure plot. Possible values:
                - `fermie`: shift all eigenvalues to have zero energy at the Fermi energy (`self.fermie`).
                -  Number e.g e0=0.5: shift all eigenvalues to have zero energy at 0.5 eV
                -  None: Don't shift energies, equivalent to e0=0
            ax_list: List of |matplotlib-Axes| for plot. If None, new figure is produced.
            xlims: Set the data limits for the x-axis. Accept tuple e.g. ``(left, right)``
                   or scalar e.g. ``left``. If left (right) is None, default values are used.
            sharey: True if y-axis should be shared.
            fontsize: Legend and title fontsize.

        Returns: |matplotlib-Figure|
        """
        with_fields = QPState.get_fields_for_plot(with_fields, exclude_fields)

        # Because qplist does not have the fermi level.
        fermie = self.ebands.get_e0(e0) if e0 is not None else None
        for spin in range(self.nsppol):
            fig = self.qplist_spin[spin].plot_qps_vs_e0(
                with_fields=with_fields, exclude_fields=exclude_fields, fermie=fermie,
                xlims=xlims, sharey=sharey, ax_list=ax_list, fontsize=fontsize,
                marker=self.marker_spin[spin], show=False, **kwargs)
            ax_list = fig.axes

        return fig

    @add_fig_kwargs
    def plot_spectral_functions(self, include_bands=None, fontsize=8, ax_list=None, **kwargs) -> Figure:
        """
        Plot the spectral function for all k-points, bands and spins available in the SIGRES file.

        Args:
            include_bands: List of bands to include. None means all.
            fontsize: Legend and title fontsize.

        Returns: |matplotlib-Figure|
        """
        if include_bands is not None:
            include_bands = set(include_bands)

        # Build grid of plots.
        nrows, ncols = len(self.sigma_kpoints), 1
        ax_list, fig, plt = get_axarray_fig_plt(ax_list, nrows=nrows, ncols=ncols,
                                                sharex=True, sharey=False, squeeze=False)
        ax_list = np.array(ax_list).ravel()

        for ikcalc, (kcalc, ax) in enumerate(zip(self.sigma_kpoints, ax_list)):
            for spin in range(self.nsppol):
                for band in range(self.bstart_sk[spin, ikcalc], self.bstop_sk[spin, ikcalc]):
                    if include_bands and band not in include_bands: continue
                    sigw = self.read_sigee_skb(spin, kcalc, band)
                    label = r"$A(\omega)$: band: %d, spin: %d" % (band, spin)
                    sigw.plot_ax(ax, what="a", label=label, fontsize=fontsize, **kwargs)

                # Show KS gap as filled area.
                #self.ebands.add_fundgap_span(ax, spin)

            ax.set_title("k-point: %s" % repr(sigw.kpoint), fontsize=fontsize)
            ax.set_ylabel(r"$A(\omega)$ (1/eV)")

        return fig

    @add_fig_kwargs
    def plot_eigvec_qp(self, spin=0, kpoint=None, band=None, **kwargs) -> Figure:
        """

        Args:
            spin: Spin index
            kpoint: K-point in self-energy. Accepts |Kpoint|, vector or index.
                If None, all k-points for the given ``spin`` are shown.
            band: band index. If None all bands are displayed else
                only <KS_b|QP_{b'}> for the given b.
            kwargs: Passed to plot method of :class:`ArrayPlotter`.

        Returns: |matplotlib-Figure|
        """
        plotter = ArrayPlotter()
        if kpoint is None:
            for kpoint in self.ibz:
                ksqp_arr = self.r.read_eigvec_qp(spin, kpoint, band=band)
                plotter.add_array(repr(kpoint), ksqp_arr)
            return plotter.plot(show=False, **kwargs)

        else:
            ksqp_arr = self.r.read_eigvec_qp(spin, kpoint, band=band)
            plotter.add_array(repr(kpoint), ksqp_arr)
            return plotter.plot(show=False, **kwargs)

    @add_fig_kwargs
    def plot_qpbands_ibz(self, e0="fermie", colormap="jet", ylims=None, fontsize=8, **kwargs) -> Figure:
        r"""
        Plot the KS band structure in the IBZ with the QP energies.

        Args:
            e0: Option used to define the zero of energy in the band structure plot.
            colormap: matplotlib color map.
            ylims: Set the data limits for the y-axis. Accept tuple e.g. ``(left, right)``
                   or scalar e.g. ``left``. If left (right) is None, default values are used.
            fontsize: Legend and title fontsize.

        Returns: |matplotlib-Figure|
        """
        # Map sigma_kpoints to ebands.kpoints
        kcalc2ibz = np.empty(self.nkcalc, dtype=int)
        for ikc, sigkpt in enumerate(self.sigma_kpoints):
            kcalc2ibz[ikc] = self.ebands.kpoints.index(sigkpt)

        # TODO: It seems there's a minor issue with fermie if SCF band structure.
        e0 = self.ebands.get_e0(e0)
        #print("e0",e0, self.ebands.fermie)

        # Build grid with (1, nsppol) plots.
        nrows, ncols = 1, self.nsppol
        ax_list, fig, plt = get_axarray_fig_plt(None, nrows=nrows, ncols=ncols,
                                                sharex=True, sharey=True, squeeze=False)
        ax_list = np.array(ax_list).ravel()
        cmap = plt.get_cmap(colormap)

        # Read QP energies: Fortran egw(nbnds,nkibz,nsppol)
        qpes = self.r.read_value("egw", cmode="c") # * units.Ha_to_eV
        band_range = (self.r.max_bstart, self.r.min_bstop)

        nb = self.r.min_bstop - self.r.min_bstart
        for spin, ax in zip(range(self.nsppol), ax_list):
            # Plot KS bands in the band range included in self-energy calculation.
            self.ebands.plot(ax=ax, e0=e0, spin=spin, band_range=band_range, show=False)
            # Extract QP in IBZ
            yvals = qpes[spin, kcalc2ibz, :].real - e0
            # Add (scattered) QP energies for the calculated k-points.
            for band in range(self.r.max_bstart, self.r.min_bstop):
                ax.scatter(kcalc2ibz, yvals[:, band],
                           color=cmap(band / nb), alpha=0.6, marker="o", s=20,
                )
            set_axlims(ax, ylims, "y")

        return fig

    @add_fig_kwargs
    def plot_ksbands_with_qpmarkers(self, qpattr="qpeme0", e0="fermie", fact=1000, ax=None, **kwargs) -> Figure:
        """
        Plot the KS energies as function of k-points and add markers whose size
        is proportional to the QPState attribute ``qpattr``

        Args:
            qpattr: Name of the QP attribute to plot. See :class:`QPState`.
            e0: Option used to define the zero of energy in the band structure plot. Possible values:
                - ``fermie``: shift all eigenvalues to have zero energy at the Fermi energy (``self.fermie``).
                -  Number e.g ``e0 = 0.5``: shift all eigenvalues to have zero energy at 0.5 eV
                -  None: Don't shift energies, equivalent to ``e0 = 0``
            fact: Markers are multiplied by this factor.
            ax: |matplotlib-Axes| or None if a new figure should be created.

        Returns: |matplotlib-Figure|
        """
        ax, fig, plt = get_ax_fig_plt(ax=ax)

        gwband_range = self.min_bstart, self.max_bstop
        self.ebands.plot(band_range=gwband_range, e0=e0, ax=ax, show=False, **kwargs)

        e0 = self.ebands.get_e0(e0)
        marker = self.get_marker(qpattr)
        pos, neg = marker.posneg_marker()

        # Use different symbols depending on the value of s. Cannot use negative s.
        if pos:
            ax.scatter(pos.x, pos.y - e0, s=np.abs(pos.s) * fact, marker="^", label=qpattr + " >0")
        if neg:
            ax.scatter(neg.x, neg.y - e0, s=np.abs(neg.s) * fact, marker="v", label=qpattr + " <0")

        return fig

    def get_dataframe(self, ignore_imag=False) -> pd.DataFrame:
        """
        Returns |pandas-DataFrame| with QP results for all k-points included in the GW calculation

        Args:
            ignore_imag: Only real part is returned if ``ignore_imag``.
        """
        df_list = []
        for spin in range(self.nsppol):
            for kcalc in self.sigma_kpoints:
                df_sk = self.get_dataframe_sk(spin, kcalc, ignore_imag=ignore_imag)
                df_list.append(df_sk)

        return pd.concat(df_list)

    # FIXME: To maintain previous interface.
    #to_dataframe = get_dataframe

    def get_dataframe_sk(self,
                         spin: int,
                         kpoint: KptSelect,
                         index=None,
                         ignore_imag=False,
                         with_params=True) -> pd.Dataframe:
        """
        Returns |pandas-DataFrame| with the QP results for the given (spin, k-point).

        Args:
            ignore_imag: Only real part is returned if ``ignore_imag``.
            with_params: True to include convergence parameters.
        """
        rows, bands = [], []
        ikcalc = self.r.kpt2ikcalc(kpoint)

        # bstart and bstop depends on kpoint.
        for band in range(self.bstart_sk[spin, ikcalc], self.bstop_sk[spin, ikcalc]):
            bands.append(band)
            # Build dictionary with the QP results.
            qpstate = self.r.read_qp(spin, kpoint, band, ignore_imag=ignore_imag)
            d = qpstate.as_dict()
            if with_params:
                # Add other entries that may be useful when comparing different calculations.
                d.update(self.params)
            rows.append(d)

        index = len(bands) * [index] if index is not None else bands
        return pd.DataFrame(rows, index=index, columns=list(rows[0].keys()))

    @add_fig_kwargs
    def plot_sigma_imag_axis(self,
                             kpoint: KptSelect,
                             spin: int = 0,
                             ax_list=None,
                             fontsize: int = 8,
                             **kwargs) -> Figure:
        """
        Plot the self-energy along the imaginary frequency axis.
        Requires GW calculations with analytic continuation

        Args:
            kpoint: K-point in self-energy. Accepts |Kpoint|, vector or index.
            spin: Spin index.
            ax_list: List of |matplotlib-Axes| or None if a new figure should be created.
            fontsize: Legend and title fontsize.

        Returns: |matplotlib-Figure|
        """
        # On disk we have the following arrays:
        # Matrix elements of $\Sigma_c$ along the imaginary axis.
        # Only used in case of analytical continuation.
        # NB: Values in the netcdf file are in eV

        # sigcmesi(b1gw:b2gw, nkibz, nomega_i, nsppol*nsig_ab))
        # nctkarr_t('sigxcmesi', "dp", 'cplex, nbgw, number_of_kpoints, nomega_i, ndim_sig'),&
        # nctkarr_t('sigcmesi', "dp",'cplex, nbgw, number_of_kpoints, nomega_i, ndim_sig'),&
        # nctkarr_t('omega_i', "dp", 'cplex, nomega_i')])

        var = self.r.read_variable("sigcmesi")
        wmesh_ev = self.r.read_value("omega_i")[:, 1]

        ikcalc = self.r.kpt2ikcalc(kpoint)
        ik_ibz = self.r.kpt2ibz(kpoint)

        #sigma_band = {}
        #for band in range(self.bstart_sk[spin, ikcalc], self.bstop_sk[spin, ikcalc]):
        #    sigma_band[band] = self.read_sigee_skb(spin, kpoint, band)

        nrows, ncols = 2, 1
        ax_list, fig, plt = get_axarray_fig_plt(ax_list, nrows=nrows, ncols=ncols,
                                                sharex=True, sharey=False, squeeze=False)
        ax_list = np.array(ax_list).ravel()
        re_ax, im_ax = ax_list

        for band in range(self.bstart_sk[spin, ikcalc], self.bstop_sk[spin, ikcalc]):
            ib_gw = band - self.min_bstart
            sigma = var[spin, :, ik_ibz, ib_gw, 0] + 1j*var[spin, :, ik_ibz, ib_gw, 1]
            re_ax.plot(wmesh_ev, sigma.real, label=f"band: {band}")
            im_ax.plot(wmesh_ev, sigma.imag, label=f"band: {band}")

        re_ax.set_ylabel(r"$\Re{\Sigma_c}(i\omega)$ (eV)")
        im_ax.set_ylabel(r"$\Im{\Sigma_c}(i\omega)$ (eV)")
        set_grid_legend(ax_list, fontsize, xlabel=r"$i\omega$ (eV)")

        return fig

    #def plot_mlda_to_qps(self, spin, kpoint, *args, **kwargs):
    #    matrix = self.r.read_mlda_to_qps(spin, kpoint)
    #    return plot_matrix(matrix, *args, **kwargs)

    def interpolate(self,
                    lpratio=5,
                    ks_ebands_kpath=None,
                    ks_ebands_kmesh=None,
                    ks_degatol=1e-4,
                    vertices_names=None,
                    line_density=20,
                    filter_params=None,
                    only_corrections=False,
                    verbose=0):
        """
        Interpolate the GW corrections in k-space on a k-path and, optionally, on a k-mesh.

        Args:
            lpratio: Ratio between the number of star functions and the number of ab-initio k-points.
                The default should be OK in many systems, larger values may be required for accurate derivatives.
            ks_ebands_kpath: KS |ElectronBands| on a k-path. If present,
                the routine interpolates the QP corrections and apply them on top of the KS band structure
                This is the recommended option because QP corrections are usually smoother than the
                QP energies and therefore easier to interpolate. If None, the QP energies are interpolated
                along the path defined by ``vertices_names`` and ``line_density``.
            ks_ebands_kmesh: KS |ElectronBands| on a homogeneous k-mesh. If present, the routine
                interpolates the corrections on the k-mesh (used to compute QP the DOS)
            ks_degatol: Energy tolerance in eV. Used when either ``ks_ebands_kpath`` or ``ks_ebands_kmesh`` are given.
                KS energies are assumed to be degenerate if they differ by less than this value.
                The interpolator may break band degeneracies (the error is usually smaller if QP corrections
                are interpolated instead of QP energies). This problem can be partly solved by averaging
                the interpolated values over the set of KS degenerate states.
                A negative value disables this ad-hoc symmetrization.
            vertices_names: Used to specify the k-path for the interpolated QP band structure
                when ``ks_ebands_kpath`` is None.
                It's a list of tuple, each tuple is of the form (kfrac_coords, kname) where
                kfrac_coords are the reduced coordinates of the k-point and kname is a string with the name of
                the k-point. Each point represents a vertex of the k-path. ``line_density`` defines
                the density of the sampling. If None, the k-path is automatically generated according
                to the point group of the system.
            line_density: Number of points in the smallest segment of the k-path. Used with ``vertices_names``.
            filter_params: TO BE DESCRIBED
            only_corrections: If True, the output contains the interpolated QP corrections instead of the QP energies.
                Available only if ks_ebands_kpath and/or ks_ebands_kmesh are used.
            verbose: Verbosity level

        Returns:

            :class:`namedtuple` with the following attributes::

                * qp_ebands_kpath: |ElectronBands| with the QP energies interpolated along the k-path.
                * qp_ebands_kmesh: |ElectronBands| with the QP energies interpolated on the k-mesh.
                    None if ``ks_ebands_kmesh`` is not passed.
                * ks_ebands_kpath: |ElectronBands| with the KS energies interpolated along the k-path.
                * ks_ebands_kmesh: |ElectronBands| with the KS energies on the k-mesh..
                    None if ``ks_ebands_kmesh`` is not passed.
                * interpolator: |SkwInterpolator| object.
        """
        # TODO: Consistency check.
        errlines = []
        eapp = errlines.append
        if len(self.sigma_kpoints) != len(self.ibz):
            eapp("QP energies should be computed for all k-points in the IBZ but nkibz != nkptgw")
        if len(self.sigma_kpoints) == 1:
            eapp("QP Interpolation requires nkptgw > 1.")
        #if (np.any(self.bstop_sk[0, 0] != self.bstop_sk):
        #    cprint("Highest bdgw band is not constant over k-points. QP Bands will be interpolated up to...")
        #if (np.any(self.bstart_sk[0, 0] != self.bstart_sk):
        #if (np.any(self.bstart_sk[0, 0] != 0):
        if errlines:
            raise ValueError("\n".join(errlines))

        # Get symmetries from abinit spacegroup (read from file).
        abispg = self.structure.abi_spacegroup
        fm_symrel = [s for (s, afm) in zip(abispg.symrel, abispg.symafm) if afm == 1]

        if ks_ebands_kpath is None:
            # Generate k-points for interpolation. Will interpolate all bands available in the sigres file.
            bstart, bstop = 0, -1
            if vertices_names is None:
                vertices_names = [(k.frac_coords, k.name) for k in self.structure.hsym_kpoints]
            kpath = Kpath.from_vertices_and_names(self.structure, vertices_names, line_density=line_density)
            kfrac_coords, knames = kpath.frac_coords, kpath.names

        else:
            # Use list of k-points from ks_ebands_kpath.
            ks_ebands_kpath = ElectronBands.as_ebands(ks_ebands_kpath)
            kfrac_coords = [k.frac_coords for k in ks_ebands_kpath.kpoints]
            knames = [k.name for k in ks_ebands_kpath.kpoints]

            # Find the band range for the interpolation.
            bstart, bstop = 0, ks_ebands_kpath.nband
            bstop = min(bstop, self.min_bstop)
            if ks_ebands_kpath.nband < self.min_bstop:
                cprint("Number of bands in KS band structure smaller than the number of bands in GW corrections", "red")
                cprint("Highest GW bands will be ignored", "red")

            if not ks_ebands_kpath.kpoints.is_path:
                cprint("Energies in ks_ebands_kpath should be along a k-path!", "red")

        # Interpolate QP energies if ks_ebands_kpath is None else interpolate QP corrections
        # and re-apply them on top of the KS band structure.
        gw_kcoords = [k.frac_coords for k in self.sigma_kpoints]

        # Read GW energies from file (real part) and compute corrections if ks_ebands_kpath.
        # This is the section in which the fileoformat (SIGRES.nc, GWR.nc) enters into play...
        egw_rarr = self.r.read_value("egw", cmode="c").real
        if ks_ebands_kpath is not None:
            if ks_ebands_kpath.structure != self.structure:
                cprint("sigres.structure and ks_ebands_kpath.structures differ. Check your files!", "red")
            egw_rarr -= self.r.read_value("e0")

        # Note there's no guarantee that the sigma_kpoints and the corrections have the same k-point index.
        # Be careful because the order of the k-points and the band range stored in the SIGRES file may differ ...
        qpdata = np.empty(egw_rarr.shape)
        for gwk in self.sigma_kpoints:
            ik_ibz = self.r.kpt2ibz(gwk)
            for spin in range(self.nsppol):
                qpdata[spin, ik_ibz, :] = egw_rarr[spin, ik_ibz, :]

        # Build interpolator for QP corrections.
        from abipy.core.skw import SkwInterpolator
        cell = (self.structure.lattice.matrix, self.structure.frac_coords, self.structure.atomic_numbers)
        qpdata = qpdata[:, :, bstart:bstop]
        # Old sigres files do not have kptopt.
        has_timrev = has_timrev_from_kptopt(self.r.read_value("kptopt", default=1))

        skw = SkwInterpolator(lpratio, gw_kcoords, qpdata, self.ebands.fermie, self.ebands.nelect,
                              cell, fm_symrel, has_timrev,
                              filter_params=filter_params, verbose=verbose)

        if ks_ebands_kpath is None:
            # Interpolate QP energies.
            eigens_kpath = skw.interp_kpts(kfrac_coords).eigens
        else:
            # Interpolate QP energies corrections and add them to KS.
            ref_eigens = ks_ebands_kpath.eigens[:, :, bstart:bstop]
            qp_corrs = skw.interp_kpts_and_enforce_degs(kfrac_coords, ref_eigens, atol=ks_degatol).eigens
            eigens_kpath = qp_corrs if only_corrections else ref_eigens + qp_corrs

        # Build new ebands object with k-path.
        kpts_kpath = Kpath(self.structure.reciprocal_lattice, kfrac_coords, weights=None, names=knames)
        occfacts_kpath = np.zeros(eigens_kpath.shape)

        # Finding the new Fermi level of the interpolated bands is not trivial, in particular if metals
        # because one should first interpolate the QP bands on a mesh. Here I align the QP bands
        # at the HOMO of the KS bands.
        homos = ks_ebands_kpath.homos if ks_ebands_kpath is not None else self.ebands.homos
        qp_fermie = max([eigens_kpath[e.spin, e.kidx, e.band] for e in homos])
        #qp_fermie = self.ebands.fermie; qp_fermie = 0.0

        qp_ebands_kpath = ElectronBands(self.structure, kpts_kpath, eigens_kpath, qp_fermie, occfacts_kpath,
                                        self.ebands.nelect, self.ebands.nspinor, self.ebands.nspden,
                                        smearing=self.ebands.smearing)

        qp_ebands_kmesh = None
        if ks_ebands_kmesh is not None:
            # Interpolate QP corrections on the same k-mesh as the one used in the KS run.
            ks_ebands_kmesh = ElectronBands.as_ebands(ks_ebands_kmesh)
            if bstop > ks_ebands_kmesh.nband:
                raise ValueError("Not enough bands in ks_ebands_kmesh, found %s, minimum expected %d\n" % (
                    ks_ebands_kmesh.nband, bstop))
            if ks_ebands_kpath.structure != self.structure:
                cprint("sigres.structure and ks_ebands_kpath.structures differ. Check your files!", "red")
            if not ks_ebands_kmesh.kpoints.is_ibz:
                cprint("Energies in ks_ebands_kmesh should be given in the IBZ", "red")

            # K-points and weights for DOS are taken from ks_ebands_kmesh.
            dos_kcoords = [k.frac_coords for k in ks_ebands_kmesh.kpoints]
            dos_weights = [k.weight for k in ks_ebands_kmesh.kpoints]

            # Interpolate QP corrections from bstart to bstop.
            ref_eigens = ks_ebands_kmesh.eigens[:, :, bstart:bstop]
            qp_corrs = skw.interp_kpts_and_enforce_degs(dos_kcoords, ref_eigens, atol=ks_degatol).eigens
            eigens_kmesh = qp_corrs if only_corrections else ref_eigens + qp_corrs

            # Build new ebands object with k-mesh.
            kpts_kmesh = IrredZone(self.structure.reciprocal_lattice, dos_kcoords, weights=dos_weights,
                                   names=None, ksampling=ks_ebands_kmesh.kpoints.ksampling)
            occfacts_kmesh = np.zeros(eigens_kmesh.shape)
            qp_ebands_kmesh = ElectronBands(self.structure, kpts_kmesh, eigens_kmesh, qp_fermie, occfacts_kmesh,
                                            self.ebands.nelect, self.ebands.nspinor, self.ebands.nspden,
                                            smearing=self.ebands.smearing)

        return dict2namedtuple(qp_ebands_kpath=qp_ebands_kpath,
                               qp_ebands_kmesh=qp_ebands_kmesh,
                               ks_ebands_kpath=ks_ebands_kpath,
                               ks_ebands_kmesh=ks_ebands_kmesh,
                               interpolator=skw,
                               )

    def yield_figs(self, **kwargs):  # pragma: no cover
        """
        This function *generates* a predefined list of matplotlib figures with minimal input from the user.
        Used in abiview.py to get a quick look at the results.
        """
        yield self.plot_qpgaps(show=False)
        yield self.plot_qps_vs_e0(show=False)
        #yield self.plot_qpbands_ibz(show=False)
        #yield self.plot_ksbands_with_qpmarkers(show=False)
        if self.has_spectral_function:
            yield self.plot_spectral_functions(include_bands=None, show=False)

    def write_notebook(self, nbpath=None):
        """
        Write a jupyter_ notebook to ``nbpath``. If nbpath is None, a temporay file in the current
        working directory is created. Return path to the notebook.
        """
        nbformat, nbv, nb = self.get_nbformat_nbv_nb(title=None)

        nb.cells.extend([
            nbv.new_code_cell("sigres = abilab.abiopen('%s')" % self.filepath),
            nbv.new_code_cell("print(sigres)"),
            nbv.new_code_cell("sigres.plot_qps_vs_e0();"),
            nbv.new_code_cell("sigres.plot_spectral_functions(spin=0, kpoint=[0, 0, 0], bands=0);"),
            nbv.new_code_cell("#sigres.plot_ksbands_with_qpmarkers(qpattr='qpeme0', fact=100);"),
            nbv.new_code_cell("r = sigres.interpolate(ks_ebands_kpath=None, ks_ebands_kmesh=None); print(r.interpolator)"),
            nbv.new_code_cell("r.qp_ebands_kpath.plot();"),
            nbv.new_code_cell("""
if r.ks_ebands_kpath is not None:
    plotter = abilab.ElectronBandsPlotter()
    plotter.add_ebands("KS", r.ks_ebands_kpath) # dos=r.ks_ebands_kmesh.get_edos())
    plotter.add_ebands("GW (interpolated)", r.qp_ebands_kpath) # dos=r.qp_ebands_kmesh.get_edos()))
    plotter.ipw_select_plot()"""),
        ])

        return self._write_nb_nbpath(nb, nbpath)


class SigresReader(ETSF_Reader):
    r"""
    This object provides method to read data from the SIGRES file produced ABINIT.

    .. rubric:: Inheritance Diagram
    .. inheritance-diagram:: SigresReader
    """

    # See 70gw/m_sigma_results.F90

    # Name of the diagonal matrix elements stored in the file.
    # b1gw:b2gw,nkibz,nsppol*nsig_ab))
    #_DIAGO_MELS = [
    #    "sigxme",
    #    "vxcme",
    #    "vUme",
    #    "dsigmee0",
    #    "sigcmee0",
    #    "sigxcme",
    #    "ze0",
    #]

    # integer :: b1gw,b2gw      ! min and Max gw band indeces over spin and k-points (used to dimension)
    # integer :: gwcalctyp      ! Flag defining the calculation type.
    # integer :: nkptgw         ! No. of points calculated
    # integer :: nkibz          ! No. of irreducible k-points.
    # integer :: nbnds          ! Total number of bands
    # integer :: nomega_r       ! No. of real frequencies for the spectral function.
    # integer :: nomega_i       ! No. of frequencies along the imaginary axis.
    # integer :: nomega4sd      ! No. of real frequencies to evaluate the derivative of $\Sigma(E)$.
    # integer :: nsig_ab        ! 1 if nspinor=1,4 for noncollinear case.
    # integer :: nsppol         ! No. of spin polarizations.
    # integer :: usepawu        ! 1 if we are using LDA+U as starting point (only for PAW)

    # real(dp) :: deltae       ! Frequency step for the calculation of d\Sigma/dE
    # real(dp) :: maxomega4sd  ! Max frequency around E_ks for d\Sigma/dE.
    # real(dp) :: maxomega_r   ! Max frequency for spectral function.
    # real(dp) :: scissor_ene  ! Scissor energy value. zero for None.

    # integer,pointer :: maxbnd(:,:)
    # ! maxbnd(nkptgw,nsppol)
    # ! Max band index considered in GW for this k-point.

    # integer,pointer :: minbnd(:,:)
    # ! minbnd(nkptgw,nsppol)
    # ! Min band index considered in GW for this k-point.

    # real(dp),pointer :: degwgap(:,:)
    # ! degwgap(nkibz,nsppol)
    # ! Difference btw the QPState and the KS optical gap.

    # real(dp),pointer :: egwgap(:,:)
    # ! egwgap(nkibz,nsppol))
    # ! QPState optical gap at each k-point and spin.

    # real(dp),pointer :: en_qp_diago(:,:,:)
    # ! en_qp_diago(nbnds,nkibz,nsppol))
    # ! QPState energies obtained from the diagonalization of the Hermitian approximation to Sigma (QPSCGW)

    # real(dp),pointer :: e0(:,:,:)
    # ! e0(nbnds,nkibz,nsppol)
    # ! KS eigenvalues for each band, k-point and spin. In case of self-consistent?

    # real(dp),pointer :: e0gap(:,:)
    # ! e0gap(nkibz,nsppol),
    # ! KS gap at each k-point, for each spin.

    # real(dp),pointer :: omega_r(:)
    # ! omega_r(nomega_r)
    # ! real frequencies used for the self energy.

    # real(dp),pointer :: kptgw(:,:)
    # ! kptgw(3,nkptgw)
    # ! ! TODO there is a similar array in sigma_parameters
    # ! List of calculated k-points.

    # real(dp),pointer :: sigxme(:,:,:)
    # ! sigxme(b1gw:b2gw,nkibz,nsppol*nsig_ab))
    # ! Diagonal matrix elements of $\Sigma_x$ i.e $\<nks|\Sigma_x|nks\>$

    # real(dp),pointer :: vxcme(:,:,:)
    # ! vxcme(b1gw:b2gw,nkibz,nsppol*nsig_ab))
    # ! $\<nks|v_{xc}[n_val]|nks\>$ matrix elements of vxc (valence-only contribution).

    # real(dp),pointer :: vUme(:,:,:)
    # ! vUme(b1gw:b2gw,nkibz,nsppol*nsig_ab))
    # ! $\<nks|v_{U}|nks\>$ for LDA+U.

    # complex(dpc),pointer :: degw(:,:,:)
    # ! degw(b1gw:b2gw,nkibz,nsppol))
    # ! Difference between the QPState and the KS energies.

    # complex(dpc),pointer :: dsigmee0(:,:,:)
    # ! dsigmee0(b1gw:b2gw,nkibz,nsppol*nsig_ab))
    # ! Derivative of $\Sigma_c(E)$ calculated at the KS eigenvalue.

    # complex(dpc),pointer :: egw(:,:,:)
    # ! egw(nbnds,nkibz,nsppol))
    # ! QPState energies, $\epsilon_{nks}^{QPState}$.

    # complex(dpc),pointer :: eigvec_qp(:,:,:,:)
    # ! eigvec_qp(nbnds,nbnds,nkibz,nsppol))
    # ! Expansion of the QPState amplitude in the KS basis set.

    # complex(dpc),pointer :: hhartree(:,:,:,:)
    # ! hhartree(b1gw:b2gw,b1gw:b2gw,nkibz,nsppol*nsig_ab)
    # ! $\<nks|T+v_H+v_{loc}+v_{nl}|mks\>$

    # complex(dpc),pointer :: sigcme(:,:,:,:)
    # ! sigcme(b1gw:b2gw,nkibz,nomega_r,nsppol*nsig_ab))
    # ! $\<nks|\Sigma_{c}(E)|nks\>$ at each nomega_r frequency

    # complex(dpc),pointer :: sigmee(:,:,:)
    # ! sigmee(b1gw:b2gw,nkibz,nsppol*nsig_ab))
    # ! $\Sigma_{xc}E_{KS} + (E_{QPState}- E_{KS})*dSigma/dE_KS

    # complex(dpc),pointer :: sigcmee0(:,:,:)
    # ! sigcmee0(b1gw:b2gw,nkibz,nsppol*nsig_ab))
    # ! Diagonal mat. elements of $\Sigma_c(E)$ calculated at the KS energy $E_{KS}$

    # complex(dpc),pointer :: sigcmesi(:,:,:,:)
    # ! sigcmesi(b1gw:b2gw,nkibz,nomega_i,nsppol*nsig_ab))
    # ! Matrix elements of $\Sigma_c$ along the imaginary axis.
    # ! Only used in case of analytical continuation.

    # complex(dpc),pointer :: sigcme4sd(:,:,:,:)
    # ! sigcme4sd(b1gw:b2gw,nkibz,nomega4sd,nsppol*nsig_ab))
    # ! Diagonal matrix elements of \Sigma_c around the zeroth order eigenvalue (usually KS).

    # complex(dpc),pointer :: sigxcme(:,:,:,:)
    # ! sigxme(b1gw:b2gw,nkibz,nomega_r,nsppol*nsig_ab))
    # ! $\<nks|\Sigma_{xc}(E)|nks\>$ at each real frequency frequency.

    # complex(dpc),pointer :: sigxcmesi(:,:,:,:)
    # ! sigxcmesi(b1gw:b2gw,nkibz,nomega_i,nsppol*nsig_ab))
    # ! Matrix elements of $\Sigma_{xc}$ along the imaginary axis.
    # ! Only used in case of analytical continuation.

    # complex(dpc),pointer :: sigxcme4sd(:,:,:,:)
    # ! sigxcme4sd(b1gw:b2gw,nkibz,nomega4sd,nsppol*nsig_ab))
    # ! Diagonal matrix elements of \Sigma_xc for frequencies around the zeroth order eigenvalues.

    # complex(dpc),pointer :: ze0(:,:,:)
    # ! ze0(b1gw:b2gw,nkibz,nsppol))
    # ! renormalization factor. $(1-\dfrac{\partial\Sigma_c} {\partial E_{KS}})^{-1}$

    # complex(dpc),pointer :: omega_i(:)
    # ! omegasi(nomega_i)
    # ! Frequencies along the imaginary axis used for the analytical continuation.

    # complex(dpc),pointer :: omega4sd(:,:,:,:)
    # ! omega4sd(b1gw:b2gw,nkibz,nomega4sd,nsppol).
    # ! Frequencies used to evaluate the Derivative of Sigma.

    def __init__(self, path: str):
        self.ks_bands = ElectronBands.from_file(path)
        self.nsppol = self.ks_bands.nsppol
        super().__init__(path)

        # Read number of frequencies for Sigma along the real axis.
        try:
            self.nomega_r = self.read_dimvalue("nomega_r")
        except self.Error:
            self.nomega_r = 0

        # Read Number of frequencies for Sigma along the imag axis.
        try:
            self.nomega_i = self.read_dimvalue("nomega_i")
        except self.Error:
            self.nomega_i = 0

        # Save important quantities needed to simplify the API.
        self.structure = self.read_structure()

        self.gwcalctyp = self.read_value("gwcalctyp")
        self.usepawu = self.read_value("usepawu")

        # 1) The K-points of the homogeneous mesh.
        self.ibz = self.ks_bands.kpoints

        # 2) The K-points where QPState corrections have been calculated.
        gwred_coords = self.read_value("kptgw")
        self.sigma_kpoints = KpointList(self.structure.reciprocal_lattice, gwred_coords)
        # Find k-point name
        for kpoint in self.sigma_kpoints:
            kpoint.set_name(self.structure.findname_in_hsym_stars(kpoint))

        # minbnd[nkptgw, nsppol] gives the minimum band index computed
        # Note conversion between Fortran and python convention.
        self.bstart_sk = self.read_value("minbnd") - 1
        self.bstop_sk = self.read_value("maxbnd")
        # min and Max band index for GW corrections.
        self.min_bstart = np.min(self.bstart_sk)
        self.max_bstart = np.max(self.bstart_sk)

        self.min_bstop = np.min(self.bstop_sk)
        self.max_bstop = np.max(self.bstop_sk)

        self._egw = self.read_value("egw", cmode="c")

        # Read and save important matrix elements.
        # All these arrays are dimensioned
        # vxcme(b1gw:b2gw,nkibz,nsppol*nsig_ab))
        self._vxcme = self.read_value("vxcme")
        self._sigxme = self.read_value("sigxme")
        self._hhartree = self.read_value("hhartree", cmode="c")
        self._vUme = self.read_value("vUme")
        #if self.usepawu == 0: self._vUme.fill(0.0)

        # Complex arrays
        self._sigcmee0 = self.read_value("sigcmee0", cmode="c")
        self._ze0 = self.read_value("ze0", cmode="c")

        # Frequencies for the spectral function.
        # Note that omega_r does not depend on (s, k, b).
        if self.has_spfunc:
            self._omega_r = self.read_value("omega_r")
            self._sigcme = self.read_value("sigcme", cmode="c")
            self._sigxcme = self.read_value("sigxcme", cmode="c")

        # Self-consistent case
        self._en_qp_diago = self.read_value("en_qp_diago")
        #self._mlda_to_qp

    @property
    def has_spfunc(self) -> bool:
        """True if self contains the spectral function."""
        return self.nomega_r > 0

    def kpt2ibz(self, kpoint) -> int:
        """
        Helper function that returns the index of kpoint in the IBZ.
        Accepts |Kpoint| instance or integer

        Raise:
            `KpointsError` if kpoint cannot be found.

        .. note::

            This function is needed since arrays in the netcdf file are dimensioned
            with the total number of k-points in the IBZ.
        """
        if duck.is_intlike(kpoint): return int(kpoint)
        return self.ibz.index(kpoint)

    #def get_ikcalc_kpoint(self, kpoint) -> tuple(int, Kpoint):
    #    """
    #    Return the ikcalc index and the Kpoint
    #    """
    #    ikcalc = self.kpt2ikcalc(kpoint)
    #    kpoint = self.sigma_kpoints[ikcalc]
    #    return ikcalc, kpoint

    def kpt2ikcalc(self, kpoint) -> int:
        """
        This function returns the index of the GW k-point in (0:nkptgw)
        Used to access data in the arrays that are dimensioned [0:nkptgw] e.g. minbnd.
        """
        if duck.is_intlike(kpoint):
            return int(kpoint)
        else:
            return self.sigma_kpoints.index(kpoint)

    #def read_redc_sigma_kpoints(self):
    #    return self.read_value("kptgw")

    def read_allqps(self, ignore_imag=False) -> tuple:
        """
        Return list with ``nsppol`` items. Each item is a :class:`QPList` with the QP results

        Args:
            ignore_imag: Only real part is returned if ``ignore_imag``.
        """
        qps_spin = self.nsppol * [None]

        for spin in range(self.nsppol):
            qps = []
            for kcalc in self.sigma_kpoints:
                ikcalc = self.kpt2ikcalc(kcalc)
                for band in range(self.bstart_sk[spin, ikcalc], self.bstop_sk[spin, ikcalc]):
                    qps.append(self.read_qp(spin, kcalc, band, ignore_imag=ignore_imag))

            qps_spin[spin] = QPList(qps)

        return tuple(qps_spin)

    def read_qplist_sk(self, spin, kpoint, band=None, ignore_imag=False) -> QPList:
        """
        Read and return QPList object for the given spin, kpoint.

        Args:
            ignore_imag: Only real part is returned if ``ignore_imag``.
        """
        ikcalc = self.kpt2ikcalc(kpoint)
        bstart, bstop = self.bstart_sk[spin, ikcalc], self.bstop_sk[spin, ikcalc]

        band_list = list(range(bstart, bstop)) if band is None else \
                    [b for b in range(bstart, bstop) if b != band]

        return QPList([self.read_qp(spin, kpoint, band, ignore_imag=ignore_imag)
                      for band in band_list])

    def read_qpenes(self):
        return self._egw[:, :, :]

    def read_qp(self, spin, kpoint, band, ignore_imag=False) -> QPState:
        """
        Return QPState for the given (spin, kpoint, band).
        Only real part is returned if ``ignore_imag``.
        """
        ik_file = self.kpt2ibz(kpoint)
        # Must shift band index (see fortran code that allocates with mdbgw)
        ib_gw = band - self.min_bstart

        def ri(a):
            return np.real(a) if ignore_imag else a

        return QPState(
            spin=spin,
            kpoint=kpoint,
            band=band,
            e0=self.read_e0(spin, ik_file, band),
            qpe=ri(self._egw[spin, ik_file, band]),
            qpe_diago=ri(self._en_qp_diago[spin, ik_file, band]),
            # Note ib_gw index.
            vxcme=self._vxcme[spin, ik_file, ib_gw],
            sigxme=self._sigxme[spin, ik_file, ib_gw],
            sigcmee0=ri(self._sigcmee0[spin, ik_file, ib_gw]),
            vUme=self._vUme[spin, ik_file, ib_gw],
            ze0=ri(self._ze0[spin, ik_file, ib_gw]),
        )

    def read_qpgaps(self) -> np.ndarray:
        """Read the QP gaps. Returns [nsppol, nkibz] array with QP gaps in eV."""
        return self.read_value("egwgap")

    def read_ksgaps(self) -> np.ndarray:
        """Read the KS gaps. Returns [nsppol, nkibz] array with KS gaps in eV."""
        return self.read_value("e0gap")

    def read_e0(self, spin: int, kfile: int, band: int) -> float:
        return self.ks_bands.eigens[spin, kfile, band]

    def read_sigmaw(self, spin: int, kpoint: KptSelect, band: int) -> tuple:
        """
        Returns the real and the imaginary part of the self energy.
        """
        if not self.has_spfunc:
            raise ValueError(f"{self.path} does not contain spectral function data.")

        ik = self.kpt2ibz(kpoint)
        # Must shift band index (see fortran code that allocates with mdbgw)
        ib_gw = band - self.min_bstart
        #ib_gw = band - self.bstart_sk[spin, self.kpt2ikcalc(kpoint)]

        return self._omega_r, self._sigxcme[spin,:, ik, ib_gw]

    def read_spfunc(self, spin, kpoint, band) -> tuple[np.ndarray]:
        """
        Compute and return the mesh and the spectral function A(w).

         one/pi * ABS(AIMAG(Sr%sigcme(ib,ikibz,io,is))) /
         ( (REAL(Sr%omega_r(io)-Sr%hhartree(ib,ib,ikibz,is)-Sr%sigxcme(ib,ikibz,io,is)))**2 &
        +(AIMAG(Sr%sigcme(ib,ikibz,io,is)))**2) / Ha_eV,&
        """
        if not self.has_spfunc:
            raise ValueError("%s does not contain the spectral function" % self.path)

        ik = self.kpt2ibz(kpoint)
        # Must shift band index (see fortran code that allocates with mdbgw)
        ib_gw = band - self.min_bstart
        #ib_gw = band - self.bstart_sk[spin, self.kpt2ikcalc(kpoint)]

        aim_sigc = np.abs(self._sigcme[spin,:,ik,ib_gw].imag)
        den = np.zeros(self.nomega_r)

        for io, omega in enumerate(self._omega_r):
            den[io] = (omega - self._hhartree[spin,ik,ib_gw,ib_gw].real - self._sigxcme[spin,io,ik,ib_gw].real) ** 2 + \
                self._sigcme[spin,io,ik,ib_gw].imag ** 2

        return self._omega_r, 1./np.pi * (aim_sigc/den)

    def read_eigvec_qp(self, spin, kpoint, band=None):
        """
        Returns <KS|QPState> for the given spin, kpoint and band.
        If band is None, <KS_b|QP_{b'}> is returned.
        """
        ik = self.kpt2ibz(kpoint)
        # <KS|QPState>
        # TODO
        #eigvec_qp = self.read_value("eigvec_qp", cmode="c")
        # eigvec_qp(nbnds,nbnds,nkibz,nsppol))
        eigvec_qp = self.read_variable("eigvec_qp")
        if band is not None:
            return eigvec_qp[spin, ik, :, band, 0] + 1j * eigvec_qp[spin, ik, :, band, 1]
        else:
            return eigvec_qp[spin, ik, :, :, 0] + 1j * eigvec_qp[spin, ik, :, :, 1]

    def read_params(self) -> dict:
        """
        Read the parameters of the calculation.
        Returns dict with the value of the parameters.
        """
        param_names = [
            "ecutwfn", "ecuteps", "ecutsigx",
            "scr_nband", "sigma_nband",
            "gwcalctyp", "scissor_ene",
        ]

        # Read data and convert to scalar to avoid problems with pandas dataframes.
        # Old sigres files may not have all the metadata.
        params = {}
        for pname in param_names:
            v = self.read_value(pname, default=None)
            params[pname] = v if v is None else np.asarray(v).item()

        # Other quantities that might be subject to convergence studies.
        #params["nkibz"] = len(self.ibz)

        return params

    #def read_mlda_to_qp(self, spin, kpoint, band=None):
    #    """Returns the unitary transformation KS --> QPS"""
    #    ik = self.kpt2ibz(kpoint)
    #    if band is not None:
    #        return self._mlda_to_qp[spin,ik,:,band]
    #    else:
    #        return self._mlda_to_qp[spin,ik,:,:]

    #def read_qprhor(self):
    #    """Returns the QP density in real space."""


class SigresRobot(Robot, RobotWithEbands):
    """
    This robot analyzes the results contained in multiple SIGRES.nc files.

    .. rubric:: Inheritance Diagram
    .. inheritance-diagram:: SigresRobot
    """
    # Try to have API similar to SigEPhRobot
    EXT = "SIGRES"

    def __init__(self, *args):
        super().__init__(*args)
        if len(self.abifiles) in (0, 1): return

        # TODO
        # Check dimensions and self-energy states and issue warning.
        warns = []; wapp = warns.append
        nc0 = self.abifiles[0]
        same_nsppol, same_nkcalc = True, True
        if any(nc.nsppol != nc0.nsppol for nc in self.abifiles):
            same_nsppol = False
            wapp("Comparing ncfiles with different values of nsppol.")
        if any(nc.nkcalc != nc0.nkcalc for nc in self.abifiles):
            same_nkcalc = False
            wapp("Comparing ncfiles with different number of k-points in self-energy. Doh!")

        if same_nsppol and same_nkcalc:
            # FIXME
            # Different values of bstart_sk are difficult to handle
            # Because the high-level API assumes an absolute global index
            # Should decide how to treat this case: either raise or interpret band as an absolute band index.
            if any(np.any(nc.r.bstart_sk != nc0.r.bstart_sk) for nc in self.abifiles):
                wapp("Comparing ncfiles with different values of bstart_sk")
            if any(np.any(nc.r.bstop_sk != nc0.r.bstop_sk) for nc in self.abifiles):
                wapp("Comparing ncfiles with different values of bstop_sk")

        if warns:
            for w in warns:
                cprint(w, color="yellow")

    def _check_dims_and_params(self) -> None:
        """Test that nsppol, sigma_kpoints, are consistent."""
        if not len(self.abifiles) > 1:
            return 0

        nc0 = self.abifiles[0]
        errors = []
        eapp = errors.append

        if any(nc.nsppol != nc0.nsppol for nc in self.abifiles[1:]):
            eapp("Files with different values of `nsppol`")

        if any(nc.nkcalc != nc0.nkcalc for nc in self.abifiles[1:]):
            eapp("Files with different values of `nkcalc`")
        else:
            for nc in self.abifiles[1:]:
                for k0, k1 in zip(nc0.sigma_kpoints, nc.sigma_kpoints):
                    if k0 != k1:
                        eapp("Files with different values of `sigma_kpoints`")

        if errors:
            raise ValueError("Cannot compare multiple SIGRES.nc files. Reason:\n %s" % "\n".join(errors))

    def merge_dataframes_sk(self, spin, kpoint, **kwargs):
        for i, (label, sigr) in enumerate(self.items()):
            frame = sigr.get_dataframe_sk(spin, kpoint, index=label)
            if i == 0:
                table = frame
            else:
                #table = table.append(frame)
                table = pd.concat([table, frame], ignore_index=True)

        return table

    def get_qpgaps_dataframe(self, spin=None, kpoint=None, with_geo=False, abspath=False, funcs=None, **kwargs):
        """
        Return a |pandas-DataFrame| with the QP gaps for all files in the robot.

        Args:
            spin: Spin index.
            kpoint
            with_geo: True if structure info should be added to the dataframe
            abspath: True if paths in index should be absolute. Default: Relative to getcwd().
            funcs: Function or list of functions to execute to add more data to the DataFrame.
                Each function receives a |SigresFile| object and returns a tuple (key, value)
                where key is a string with the name of column and value is the value to be inserted.
        """
        # TODO: Ideally one should select the k-point for which we have the fundamental gap for the given spin
        # TODO: In principle the SIGRES might have different k-points
        if spin is None: spin = 0
        if kpoint is None: kpoint = 0

        attrs = [
            "nsppol",
            #"nspinor", "nspden", #"ecut", "pawecutdg",
            #"tsmear", "nkibz",
        ] + kwargs.pop("attrs", [])

        rows, row_names = [], []
        for label, sigres in self.items():
            row_names.append(label)
            d = {}
            for aname in attrs:
                d[aname] = getattr(sigres, aname, None)

            qpgap = sigres.get_qpgap(spin, kpoint)
            d.update({"qpgap": qpgap})

            # Add convergence parameters
            d.update(sigres.params)

            # Add info on structure.
            if with_geo:
                d.update(sigres.structure.get_dict4pandas(with_spglib=True))

            # Execute functions.
            if funcs is not None: d.update(self._exec_funcs(funcs, sigres))
            rows.append(d)

        row_names = row_names if not abspath else self._to_relpaths(row_names)
        return pd.DataFrame(rows, index=row_names, columns=list(rows[0].keys()))

    def get_fit_gaps_vs_ecuteps(self, spin, kpoint, plot_qpmks=True, slice_data=None, fontsize=12):
        """
        Fit QP direct gaps as a function of ecuteps using Eq. 16 of http://dx.doi.org/10.1063/1.4900447
        to extrapolate results for ecuteps --> +oo.

        Args:
            spin: Spin index (0 or 1)
            kpoint: K-point in self-energy. Accepts |Kpoint|, vector or k-point index.
            plot_qpmks: If False, plot QP_gap else (QP_gap - KS_gap) i.e. gap correction
            slice_data: Python slice object. Used to downsample data points.
                None to use all files of the SigResRobot.
            fontsize: legend and label fontsize.

        Return: TODO
        """
        # Make sure that nsppol, sigma_kpoints are consistent.
        self._check_dims_and_params()

        # Get dimensions and index of the k-point in the sigma_nk array.
        nc0 = self.abifiles[0]
        nsppol, sigma_kpoints = nc0.nsppol, nc0.sigma_kpoints
        ik = nc0.r.kpt2ikcalc(kpoint)
        kcalc = nc0.sigma_kpoints[ik]

        # Order files by ecuteps
        labels, ncfiles, params = self.sortby("ecuteps", unpack=True)
        ecuteps_vals = np.array(params)

        # Get QP and KS gaps ordered by ecuteps_vals.
        qp_gaps, ks_gaps = map(np.array, zip(*[ncfile.get_qpgap(spin, kcalc, with_ksgap=True)
            for ncfile in ncfiles]))
        ydata = qp_gaps if not plot_qpmks else qp_gaps - ks_gaps

        if slice_data is not None:
            # Allow user to select a subset of data points via python slice
            ecuteps_vals = ecuteps_vals[slice_data]
            ydata = ydata[slice_data]

        # Fit results as a function of ecuteps
        from scipy.optimize import curve_fit
        def func(x, a, b, c):
            return a * x**(-1.5) + b * x**(-2.5) + c

        popt, pcov = curve_fit(func, ecuteps_vals, ydata)

        ax, fig, plt = get_ax_fig_plt(ax=None)
        ax.plot(ecuteps_vals, ydata, 'ro', label='ab-initio data')
        min_ecuteps, max_ecuteps = ecuteps_vals.min(), ecuteps_vals.max() + 20
        xs = np.linspace(min_ecuteps, max_ecuteps, num=50)
        # Change label depending on plot_qpmks
        what = r"\Delta E_g" if plot_qpmks else r"E_g"
        ax.plot(xs, func(xs, *popt), 'b-',
                label=rf'fit: $B_3$=%5.3f, $B_5$=%5.3f, ${what} (\infty)$=%5.3f' % tuple(popt))
        ax.hlines(popt[-1], min_ecuteps, max_ecuteps, color="k")
        ax.legend(loc="best", fontsize=fontsize, shadow=True)
        ax.grid(True)
        ax.set_xlabel('ecuteps (Ha)')
        ax.set_ylabel(f'${what}$ (eV)')
        #ax.set_ylabel('$\Delta E(E_c^{\chi})$ (eV)')
        #ax.title(r'$\Delta E(E_c^{\chi}) = \Delta E_g (\infty) + B_3 * E_c^{\chi (-3/2)} + B_5* E_c^{\chi (-5/2)} $')

        #if show:
        plt.show()

        return dict2namedtuple(
                fig=fig,
                func=func,
                ecuteps_vals=ecuteps_vals,
                ydata=ydata,
                popt=popt,
                pcov=pcov,
        )

    # An alias to have a common API for robots.
    get_dataframe = get_qpgaps_dataframe

    @add_fig_kwargs
    def plot_qpgaps_convergence(self, plot_qpmks=True, sortby=None, hue=None, sharey=False, fontsize=8, **kwargs) -> Figure:
        """
        Plot the convergence of the direct QP gaps for all the k-points available in the robot.

        Args:
            plot_qpmks: If False, plot QP_gap, KS_gap else (QP_gap - KS_gap)
            sortby: Define the convergence parameter, sort files and produce plot labels.
                Can be None, string or function. If None, no sorting is performed.
                If string and not empty it's assumed that the abifile has an attribute
                with the same name and `getattr` is invoked.
                If callable, the output of sortby(abifile) is used.
            hue: Variable that define subsets of the data, which will be drawn on separate lines.
                Accepts callable or string
                If string, it's assumed that the abifile has an attribute with the same name and getattr is invoked.
                If callable, the output of hue(abifile) is used.
            sharey: True if y-axis should be shared.
            fontsize: legend and label fontsize.

        Returns: |matplotlib-Figure|
        """
        # Make sure that nsppol, sigma_kpoints are consistent.
        self._check_dims_and_params()

        nc0 = self.abifiles[0]
        nsppol, sigma_kpoints = nc0.nsppol, nc0.sigma_kpoints

        # Build grid with (nkpt, 1) plots.
        ncols, nrows = 1, len(sigma_kpoints)
        ax_list, fig, plt = get_axarray_fig_plt(None, nrows=nrows, ncols=ncols,
                                                sharex=True, sharey=sharey, squeeze=False)
        ax_list = ax_list.ravel()

        if hue is None:
            labels, ncfiles, params = self.sortby(sortby, unpack=True)
        else:
            groups = self.group_and_sortby(hue, sortby)

        for ik, (kcalc, ax) in enumerate(zip(sigma_kpoints, ax_list)):
            for spin in range(nsppol):
                ax.set_title("QP dirgap k:%s" % (repr(kcalc)), fontsize=fontsize)

                # Extract QP dirgap for [spin, ikcalc, itemp]
                if hue is None:
                    qp_gaps, ks_gaps = map(np.array, zip(*[ncfile.get_qpgap(spin, kcalc, with_ksgap=True)
                        for ncfile in ncfiles]))
                    yvals = qp_gaps if not plot_qpmks else qp_gaps - ks_gaps

                    if not is_string(params[0]):
                        ax.plot(params, yvals, marker=nc0.marker_spin[spin])
                    else:
                        # Must handle list of strings in a different way.
                        xn = range(len(params))
                        ax.plot(xn, yvals, marker=nc0.marker_spin[spin])
                        ax.set_xticks(xn)
                        ax.set_xticklabels(params, fontsize=fontsize)
                else:
                    for g in groups:
                        qp_gaps, ks_gaps = map(np.array, zip(*[ncfile.get_qpgap(spin, kcalc, with_ksgap=True)
                            for ncfile in g.abifiles]))
                        yvals = qp_gaps if not plot_qpmks else qp_gaps - ks_gaps
                        label = "%s: %s" % (self._get_label(hue), g.hvalue)
                        ax.plot(g.xvalues, qp_gaps, marker=nc0.marker_spin[spin], label=label)

            ax.grid(True)
            if ik == len(sigma_kpoints) - 1:
                ax.set_xlabel("%s" % self._get_label(sortby))
                if sortby is None: rotate_ticklabels(ax, 15)
            if ik == 0:
                if plot_qpmks:
                    ax.set_ylabel("QP-KS direct gap (eV)", fontsize=fontsize)
                else:
                    ax.set_ylabel("QP direct gap (eV)", fontsize=fontsize)

            if hue is not None:
                ax.legend(loc="best", fontsize=fontsize, shadow=True)

        return fig

    @add_fig_kwargs
    def plot_qpdata_conv_skb(self, spin, kpoint, band, sortby=None, hue=None,
                            fontsize=8, **kwargs) -> Figure:
        """
        For each file in the SIGRES robot, plot the convergence of the QP results
        for given (spin, kpoint, band)

        Args:
            spin: Spin index.
            kpoint: K-point in self-energy. Accepts |Kpoint|, vector or index.
            band: Band index.
            sortby: Define the convergence parameter, sort files and produce plot labels.
                Can be None, string or function. If None, no sorting is performed.
                If string and not empty it's assumed that the abifile has an attribute
                with the same name and `getattr` is invoked.
                If callable, the output of sortby(abifile) is used.
            hue: Variable that define subsets of the data, which will be drawn on separate lines.
                Accepts callable or string
                If string, it's assumed that the abifile has an attribute with the same name and getattr is invoked.
                If callable, the output of hue(abifile) is used.
            what_list: List of strings selecting the quantity to plot.
            fontsize: legend and label fontsize.

        Returns: |matplotlib-Figure|
        """
        # Make sure that nsppol and sigma_kpoints are consistent
        self._check_dims_and_params()

        # TODO: Add more quantities DW, Fan(0)
        # TODO: Decide how to treat complex quantities, avoid annoying ComplexWarning
        # TODO: Format for g.hvalue
        # Treat fundamental gaps
        # Quantities to plot.
        what_list = ["re_qpe", "imag_qpe", "ze0"]

        # Build grid plot.
        nrows, ncols = len(what_list), 1
        ax_list, fig, plt = get_axarray_fig_plt(None, nrows=nrows, ncols=ncols,
                                                sharex=True, sharey=False, squeeze=False)
        ax_list = ax_list.ravel()

        nc0 = self.abifiles[0]
        ik = nc0.r.kpt2ikcalc(kpoint)
        kpoint = nc0.sigma_kpoints[ik]

        # Sort and read QP data.
        if hue is None:
            labels, ncfiles, params = self.sortby(sortby, unpack=True)
            qplist = [ncfile.r.read_qp(spin, kpoint, band) for ncfile in ncfiles]
        else:
            groups = self.group_and_sortby(hue, sortby)
            qplist_group = []
            for g in groups:
                lst = [ncfile.r.read_qp(spin, kpoint, band) for ncfile in g.abifiles]
                qplist_group.append(lst)

        for i, (ax, what) in enumerate(zip(ax_list, what_list)):
            if hue is None:
                # Extract QP data.
                yvals = [getattr(qp, what) for qp in qplist]
                if not is_string(params[0]):
                    ax.plot(params, yvals, marker=nc0.marker_spin[spin])
                else:
                    # Must handle list of strings in a different way.
                    xn = range(len(params))
                    ax.plot(xn, yvals, marker=nc0.marker_spin[spin])
                    ax.set_xticks(xn)
                    ax.set_xticklabels(params, fontsize=fontsize)
            else:
                for g, qplist in zip(groups, qplist_group):
                    # Extract QP data.
                    yvals = [getattr(qp, what) for qp in qplist]
                    label = "%s: %s" % (self._get_label(hue), g.hvalue)
                    ax.plot(g.xvalues, yvals, marker=nc0.marker_spin[spin], label=label)

            ax.grid(True)
            ax.set_ylabel(what)
            if i == len(what_list) - 1:
                ax.set_xlabel("%s" % self._get_label(sortby))
                if sortby is None: rotate_ticklabels(ax, 15)
            if i == 0 and hue is not None:
                ax.legend(loc="best", fontsize=fontsize, shadow=True)

        if "title" not in kwargs:
            title = "QP results spin: %s, k:%s, band: %s" % (spin, repr(kpoint), band)
            fig.suptitle(title, fontsize=fontsize)

        return fig

    @add_fig_kwargs
    def plot_qpfield_vs_e0(self, field, sortby=None, hue=None, fontsize=8,
                           sharey=False, colormap="jet", e0="fermie", **kwargs) -> Figure:
        """
        For each file in the robot, plot one of the attributes of :class:`QpState`
        as a function of the KS energy.

        Args:
            field (str): String defining the attribute to plot.
            sharey: True if y-axis should be shared.

        .. note::

            For the meaning of the other arguments, see other robot methods.

        Returns: |matplotlib-Figure|
        """
        import matplotlib.pyplot as plt
        cmap = plt.get_cmap(colormap)

        if hue is None:
            ax_list = None
            lnp_list = self.sortby(sortby)
            for i, (label, ncfile, param) in enumerate(lnp_list):
                if sortby is not None:
                    label = "%s: %s" % (self._get_label(sortby), param)
                fig = ncfile.plot_qps_vs_e0(with_fields=list_strings(field),
                    e0=e0, ax_list=ax_list, color=cmap(i / len(lnp_list)), fontsize=fontsize,
                    sharey=sharey, label=label, show=False)
                ax_list = fig.axes
        else:
            # group_and_sortby and build (ngroups,) subplots
            groups = self.group_and_sortby(hue, sortby)
            nrows, ncols = 1, len(groups)
            ax_mat, fig, plt = get_axarray_fig_plt(None, nrows=nrows, ncols=ncols,
                                                   sharex=True, sharey=sharey, squeeze=False)
            for ig, g in enumerate(groups):
                subtitle = "%s: %s" % (self._get_label(hue), g.hvalue)
                ax_mat[0, ig].set_title(subtitle, fontsize=fontsize)
                for i, (nclabel, ncfile, param) in enumerate(g):
                    fig = ncfile.plot_qps_vs_e0(with_fields=list_strings(field),
                        e0=e0, ax_list=ax_mat[:, ig], color=cmap(i / len(g)), fontsize=fontsize,
                        sharey=sharey, label="%s: %s" % (self._get_label(sortby), param), show=False)

                if ig != 0:
                    for ax in ax_mat[:, ig]:
                        set_visible(ax, False, "ylabel")

        return fig

    @add_fig_kwargs
    def plot_selfenergy_conv(self, spin, kpoint, band, sortby=None, hue=None,
                             colormap="jet", xlims=None, fontsize=8, **kwargs) -> Figure:
        """
        Plot the convergence of the e-e self-energy wrt to the ``sortby`` parameter.
        Values can be optionally grouped by `hue`.

        Args:
            spin: Spin index.
            kpoint: K-point in self-energy (can be |Kpoint|, list/tuple or int)
            band: Band index.
            sortby: Define the convergence parameter, sort files and produce plot labels.
                Can be None, string or function. If None, no sorting is performed.
                If string and not empty it's assumed that the abifile has an attribute
                with the same name and `getattr` is invoked.
                If callable, the output of sortby(abifile) is used.
            hue: Variable that define subsets of the data, which will be drawn on separate lines.
                Accepts callable or string
                If string, it's assumed that the abifile has an attribute with the same name and getattr is invoked.
                If callable, the output of hue(abifile) is used.
            colormap: matplotlib color map.
            xlims: Set the data limits for the x-axis. Accept tuple e.g. ``(left, right)``
                   or scalar e.g. ``left``. If left (right) is None, default values are used.
            fontsize: Legend and title fontsize.

        Returns: |matplotlib-Figure|
        """
        # Make sure that nsppol and sigma_kpoints are consistent
        self._check_dims_and_params()
        import matplotlib.pyplot as plt
        cmap = plt.get_cmap(colormap)

        if hue is None:
            ax_list = None
            lnp_list = self.sortby(sortby)
            for i, (label, ncfile, param) in enumerate(lnp_list):
                sigma = ncfile.read_sigee_skb(spin, kpoint, band)
                fig = sigma.plot(ax_list=ax_list, label=label, color=cmap(i/len(lnp_list)), show=False)
                ax_list = fig.axes
        else:
            # group_and_sortby and build (3, ngroups) subplots
            groups = self.group_and_sortby(hue, sortby)
            nrows, ncols = 3, len(groups)
            ax_mat, fig, plt = get_axarray_fig_plt(None, nrows=nrows, ncols=ncols,
                                                   sharex=True, sharey=True, squeeze=False)
            for ig, g in enumerate(groups):
                subtitle = "%s: %s" % (self._get_label(hue), g.hvalue)
                ax_mat[0, ig].set_title(subtitle, fontsize=fontsize)
                for i, (nclabel, ncfile, param) in enumerate(g):
                    sigma = ncfile.read_sigee_skb(spin, kpoint, band)
                    fig = sigma.plot(ax_list=ax_mat[:, ig],
                                     label="%s: %s" % (self._get_label(sortby), param),
                                     color=cmap(i / len(g)), show=False)

            if ig != 0:
                for ax in ax_mat[:, ig]:
                    set_visible(ax, False, "ylabel")

            for ax in ax_mat.ravel():
                set_axlims(ax, xlims, "x")

        return fig

    def yield_figs(self, **kwargs):  # pragma: no cover
        """
        This function *generates* a predefined list of matplotlib figures with minimal input from the user.
        """
        yield self.plot_qpgaps_convergence(plot_qpmks=True, show=False)
        #yield self.plot_qpdata_conv_skb(spin, kpoint, band, show=False)
        #yield self.plot_qpfield_vs_e0(field, show=False)
        #yield self.plot_selfenergy_conv(spin, kpoint, band, sortby=None, hue=None, show=False)

    def write_notebook(self, nbpath=None):
        """
        Write a jupyter_ notebook to ``nbpath``. If nbpath is None, a temporay file in the current
        working directory is created. Return path to the notebook.
        """
        nbformat, nbv, nb = self.get_nbformat_nbv_nb(title=None)

        args = [(l, f.filepath) for l, f in self.items()]
        nb.cells.extend([
            #nbv.new_markdown_cell("# This is a markdown cell"),
            #nbv.new_code_cell("plotter = robot.get_ebands_plotter()"),
            nbv.new_code_cell("robot = abilab.SigresRobot(*%s)\nrobot.trim_paths()\nrobot" % str(args)),
            nbv.new_code_cell("robot.get_qpgaps_dataframe(spin=None, kpoint=None, with_geo=False)"),
            nbv.new_code_cell("robot.plot_qpgaps_convergence(plot_qpmks=True, sortby=None, hue=None);"),
            nbv.new_code_cell("#robot.plot_qpdata_conv_skb(spin=0, kpoint=0, band=0, sortby=None, hue=None);"),
            nbv.new_code_cell("robot.plot_qpfield_vs_e0(field='qpeme0', sortby=None, hue=None);"),
            nbv.new_code_cell("#robot.plot_selfenergy_conv(spin=0, kpoint=0, band=0, sortby=None, hue=None);"),
        ])

        # Mixins
        nb.cells.extend(self.get_baserobot_code_cells())
        nb.cells.extend(self.get_ebands_code_cells())

        return self._write_nb_nbpath(nb, nbpath)


class GwRobotWithDisplacedAtom(SigresRobot):
    """
    Specialized class to analyze GW or GWR calculations with displaced atom.
    """

    @classmethod
    def from_displaced_atom(cls, site_index, reduced_dir, step_ang, gw_files) -> GwRobotWithDisplacedAtom:
        """
        Build an instance from a list of SIGRES.nc or GWR.nc files.

        Args:
            site_index: Index of the site that has been displaced.
            reduced_dir: Reduced direction of the displacement.
            step_ang: Step used to displace structures in Angstrom.
            gw_files: List of paths to either SIGRES.nc or GWR.nc files.
                Files are assumed to be ordered according to the displacement.
        """
        #print(f"{gw_files}")
        new = cls(*gw_files)
        print("new = cls(*gw_files) done!")

        new.site_index = site_index
        new.reduced_dir = reduced_dir
        new.step_ang = step_ang
        new.num_points = len(gw_files)

        i0 = new.num_points // 2
        origin_structure = new[i0].structure

        ####################
        # Consistency check
        ####################

        # 1) Make sure lattice parameters and all sites other than i0 are equal.
        fixed_site_indices = [i for i in range(len(origin_structure)) if i != site_index]
        if err_str := new.has_different_structures(site_indices=fixed_site_indices):
            raise ValueError(err_str)

        # TODO
        # 2) Make sure gw_files are ordered correctly.
        #indices = np.array(range(-i0, +i0 + 1), dtype=int)
        #for idx, ieta in enumerate(indices):
        #    eta = ieta * step_ang
        #    displaced_structure = origin_structure.displace_one_site(site_index, reduced_dir, eta=eta, frac_coords=True)
        #    if displaced_structure != new[ieta].structure:
        #        raise ValueError("displaced_structure != new[ieta].structure:")

        site_list = [ncfile.structure.sites[site_index] for ncfile in new.abifiles]

        coords_diff = np.reshape([site.coords - site_list[i0].coords for site in site_list], (-1, 3))
        new.deltas = np.array([np.linalg.norm(coords) for coords in coords_diff])
        new.deltas[:i0] = -new.deltas[:i0]
        #print(f"{new.deltas=}")

        return new

    def get_dataframe_skb(self, spin: int, kpoint: KptSelect, band: int, with_params: bool = True) -> pd.DataFrame:
        """
        Return a pandas dataframe with the most important results.

        Args:
            spin: spin index.
            kpoint: K-point in self-energy. Accepts |Kpoint|, vector or index.
            band: band index.
            with_params: True if metadata should be included.
        """
        # Create list of QPState for each file.
        qp_states = [ncfile.r.read_qplist_sk(spin, kpoint, band=band)[0] for ncfile in self.abifiles]

        rows = []
        for qp_state, ncfile in zip(qp_states, self.abifiles, strict=True):
            d = qp_state.as_dict()
            # Add other entries that may be useful when comparing different calculations.
            if with_params:
                d.update(ncfile.params)
            rows.append(d)

        return pd.DataFrame(rows)

    @add_fig_kwargs
    def plot_qpdata_vs_displ_skb(self, spin: int,
                                 kpoint: KptSelect,
                                 band: int,
                                 what_list=("e0", "qpe", "sigxme", "sigcmee0", "ze0"),
                                 fontsize=8,
                                 **kwargs) -> Figure:
        """
        Plot QP results for a given spin, kpoint and band.

        Args:
            spin: Spin index.
            kpoint: K-point in self-energy. Accepts |Kpoint|, vector or index.
            band: band index. If None all bands are considered.
            what_list: Quantities to plot. See QPState for the list of supported attributes.
            fontsize: legend and label fontsize.
        """
        # Build grid plot.
        nrows, ncols = len(what_list), 1
        ax_list, fig, plt = get_axarray_fig_plt(None, nrows=nrows, ncols=ncols,
                                                sharex=True, sharey=False, squeeze=False)
        ax_list = np.array(ax_list).ravel()

        xvals = self.deltas
        #xvals = list(range(len(self)))
        x_fit = np.linspace(xvals[0], xvals[-1], num=50)

        df = self.get_dataframe_skb(spin, kpoint, band, with_params=False)

        for iax, (ax, what) in enumerate(zip(ax_list, what_list)):
            units = "" if what == "ze0" else "(eV)"
            ylabel = f"{what} {units}"
            yvals = df[what].values
            ax.plot(xvals, yvals, ls="--", marker="o", label=ylabel)

            if what not in ("ze0", ):
                # Fit a quadratic polynomial (degree 2)
                quadratic_function = np.poly1d(np.polyfit(xvals, yvals, 2))
                y_fit = quadratic_function(x_fit)
                ax.plot(x_fit, y_fit, ls="--", marker="x", label=ylabel)

            set_grid_legend(ax, fontsize,
                            xlabel=r"$\delta\, (\AA)$" if iax == len(ax_list) - 1 else None, ylabel=ylabel)

        fig.suptitle(f"{band=}, {kpoint=}, {spin=}")
        return fig
