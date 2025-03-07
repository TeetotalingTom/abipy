# coding: utf-8
"""Wrappers for ABINIT main executables"""
from __future__ import annotations

import os
import numpy as np

from monty.string import list_strings
from io import StringIO
from abipy.core.globals import get_workdir

__author__ = "Matteo Giantomassi"
__copyright__ = "Copyright 2013, The Materials Project"
__version__ = "0.1"
__maintainer__ = "Matteo Giantomassi"
__email__ = "gmatteo at gmail.com"
__status__ = "Development"
__date__ = "$Feb 21, 2013M$"

__all__ = [
    "Mrgscr",
    "Mrgddb",
    "Mrgdvdb",
    "Cut3D",
    "Fold2Bloch",
]


class ExecError(Exception):
    """Error class raised by :class:`ExecWrapper`"""


class ExecWrapper:
    """
    Base class that runs an executable in a subprocess.
    """
    Error = ExecError

    def __init__(self, manager=None, executable=None, verbose=0):
        """
        Args:
            manager: :class:`TaskManager` object responsible for the submission of the jobs.
                if manager is None, the default manager is used.
            executable: path to the executable.
            verbose: Verbosity level.
        """
        from .tasks import TaskManager
        self.manager = manager if manager is not None else TaskManager.from_user_config()
        self.manager = self.manager.to_shell_manager(mpi_procs=1)

        self.executable = executable if executable is not None else self.name
        assert os.path.basename(self.executable) == self.name
        self.verbose = int(verbose)

    def __str__(self) -> str:
        return "%s" % self.executable

    @property
    def name(self) -> str:
        return self._name

    def execute(self, workdir, exec_args=None) -> int:
        # Try to execute binary without and with mpirun.
        try:
            return self._execute(workdir, with_mpirun=True, exec_args=exec_args)
        except self.Error:
            return self._execute(workdir, with_mpirun=False, exec_args=exec_args)

    def _execute(self, workdir, with_mpirun=False, exec_args=None) -> int:
        """
        Execute the executable in a subprocess inside workdir.

        Some executables fail if we try to launch them with mpirun.
        Use with_mpirun=False to run the binary without it.
        """
        qadapter = self.manager.qadapter
        if not with_mpirun: qadapter.name = None
        if self.verbose:
            print("Working in:", workdir)

        script = qadapter.get_script_str(
            job_name=self.name,
            launch_dir=workdir,
            executable=self.executable,
            qout_path="qout_file.path",
            qerr_path="qerr_file.path",
            stdin=self.stdin_fname,
            stdout=self.stdout_fname,
            stderr=self.stderr_fname,
            exec_args=exec_args
        )

        # Write the script.
        script_file = os.path.join(workdir, "run_" + self.name + ".sh")
        with open(script_file, "wt") as fh:
            fh.write(script)
            os.chmod(script_file, 0o740)

        qjob, process = qadapter.submit_to_queue(script_file)
        self.stdout_data, self.stderr_data = process.communicate()
        self.returncode = process.returncode

        return self.returncode


class Mrgscr(ExecWrapper):
    """
    Wraps the mrgddb Fortran executable.
    """
    _name = "mrgscr"

    def merge_qpoints(self, workdir, files_to_merge, out_prefix):
        """
        Execute mrgscr inside directory `workdir` to merge `files_to_merge`.
        Produce new file with prefix `out_prefix`
        """
        # We work with absolute paths.
        files_to_merge = [os.path.abspath(s) for s in list_strings(files_to_merge)]
        nfiles = len(files_to_merge)

        if self.verbose:
            print("Will merge %d files with output_prefix %s" % (nfiles, out_prefix))
            for (i, f) in enumerate(files_to_merge):
                print(" [%d] %s" % (i, f))

        if nfiles == 1:
            raise self.Error("merge_qpoints does not support nfiles == 1")

        self.stdin_fname, self.stdout_fname, self.stderr_fname = \
            map(os.path.join, 3 * [workdir], ["mrgscr.stdin", "mrgscr.stdout", "mrgscr.stderr"])

        inp = StringIO()
        inp.write(str(nfiles) + "\n")     # Number of files to merge.
        inp.write(out_prefix + "\n")      # Prefix for the final output file:

        for filename in files_to_merge:
            inp.write(filename + "\n")   # List with the files to merge.

        inp.write("1\n")                 # Option for merging q-points.

        self.stdin_data = [s for s in inp.getvalue()]

        with open(self.stdin_fname, "w") as fh:
            fh.writelines(self.stdin_data)
            # Force OS to write data to disk.
            fh.flush()
            os.fsync(fh.fileno())

        self.execute(workdir)


class Mrgddb(ExecWrapper):
    """
    Wraps the mrgddb Fortran executable.
    """
    _name = "mrgddb"

    def merge(self, workdir, ddb_files, out_ddb, description, delete_source_ddbs=True) -> str:
        """Merge DDB file, return the absolute path of the new database in workdir."""
        # We work with absolute paths.
        ddb_files = [os.path.abspath(s) for s in list_strings(ddb_files)]
        if not os.path.isabs(out_ddb):
            out_ddb = os.path.join(os.path.abspath(workdir), os.path.basename(out_ddb))

        if self.verbose:
            print("Will merge %d files into output DDB %s" % (len(ddb_files), out_ddb))
            for i, f in enumerate(ddb_files):
                print(" [%d] %s" % (i, f))

        # Handle the case of a single file since mrgddb uses 1 to denote GS files!
        if len(ddb_files) == 1:
            with open(ddb_files[0], "r") as inh, open(out_ddb, "w") as out:
                for line in inh:
                    out.write(line)
            return out_ddb

        self.stdin_fname, self.stdout_fname, self.stderr_fname = \
            map(os.path.join, 3 * [os.path.abspath(workdir)], ["mrgddb.stdin", "mrgddb.stdout", "mrgddb.stderr"])

        inp = StringIO()
        inp.write(out_ddb + "\n")              # Name of the output file.
        inp.write(str(description) + "\n")     # Description.
        inp.write(str(len(ddb_files)) + "\n")  # Number of input DDBs.

        # Names of the DDB files.
        for fname in ddb_files:
            inp.write(fname + "\n")

        self.stdin_data = [s for s in inp.getvalue()]

        with open(self.stdin_fname, "wt") as fh:
            fh.writelines(self.stdin_data)
            # Force OS to write data to disk.
            fh.flush()
            os.fsync(fh.fileno())

        retcode = self.execute(workdir, exec_args=['--nostrict'])
        if retcode == 0 and delete_source_ddbs:
            # Remove ddb files.
            for f in ddb_files:
                try:
                    os.remove(f)
                except IOError:
                    pass

        return out_ddb


class Mrgdvdb(ExecWrapper):
    """
    Wraps the mrgdvdb Fortran executable.
    """

    _name = "mrgdv"

    def merge(self, workdir, pot_files, out_dvdb, delete_source=True) -> str:
        """
        Merge POT files containing 1st order DFPT potential
        return the absolute path of the new database in workdir.

        Args:
            delete_source: True if POT1 files should be removed after (successful) merge.
        """
        # We work with absolute paths.
        pot_files = [os.path.abspath(s) for s in list_strings(pot_files)]
        if not os.path.isabs(out_dvdb):
            out_dvdb = os.path.join(os.path.abspath(workdir), os.path.basename(out_dvdb))

        if self.verbose:
            print("Will merge %d files into output DVDB %s" % (len(pot_files), out_dvdb))
            for i, f in enumerate(pot_files):
                print(" [%d] %s" % (i, f))

        # Handle the case of a single file since mrgddb uses 1 to denote GS files!
        if len(pot_files) == 1:
            with open(pot_files[0], "r") as inh, open(out_dvdb, "w") as out:
                for line in inh:
                    out.write(line)
            return out_dvdb

        self.stdin_fname, self.stdout_fname, self.stderr_fname = \
            map(os.path.join, 3 * [os.path.abspath(workdir)], ["mrgdvdb.stdin", "mrgdvdb.stdout", "mrgdvdb.stderr"])

        inp = StringIO()
        inp.write(out_dvdb + "\n")             # Name of the output file.
        inp.write(str(len(pot_files)) + "\n")  # Number of input POT files.

        # Names of the POT files.
        for fname in pot_files:
            inp.write(fname + "\n")

        self.stdin_data = [s for s in inp.getvalue()]

        with open(self.stdin_fname, "wt") as fh:
            fh.writelines(self.stdin_data)
            # Force OS to write data to disk.
            fh.flush()
            os.fsync(fh.fileno())

        retcode = self.execute(workdir)
        if retcode == 0 and delete_source:
            # Remove pot files.
            for f in pot_files:
                try:
                    os.remove(f)
                except IOError:
                    pass

        return out_dvdb


class Cut3D(ExecWrapper):
    """
    Wraps the cut3d Fortran executable.
    """
    _name = "cut3d"

    def cut3d(self, cut3d_input, workdir) -> tuple[str, str]:
        """
        Runs cut3d with a Cut3DInput

        Args:
            cut3d_input: a Cut3DInput object.
            workdir: directory where cut3d is executed.

        Returns:
            (string) absolute path to the standard output of the cut3d execution.
            (string) absolute path to the output filepath. None if output is required.
        """
        self.stdin_fname, self.stdout_fname, self.stderr_fname = \
            map(os.path.join, 3 * [os.path.abspath(workdir)], ["cut3d.stdin", "cut3d.stdout", "cut3d.stderr"])

        cut3d_input.write(self.stdin_fname)

        retcode = self._execute(workdir, with_mpirun=False)

        if retcode != 0:
            raise RuntimeError("Error while running cut3d in %s" % workdir)

        output_filepath = cut3d_input.output_filepath

        if output_filepath is not None:
            if not os.path.isabs(output_filepath):
                output_filepath = os.path.abspath(os.path.join(workdir, output_filepath))

            if not os.path.isfile(output_filepath):
                raise RuntimeError("The file was not converted correctly in %s." % workdir)

        return self.stdout_fname, output_filepath


class Fold2Bloch(ExecWrapper):
    """
    Wraps the fold2Bloch Fortran executable.
    """
    _name = "fold2Bloch"

    def unfold(self, wfkpath, folds, workdir=None) -> str:
        workdir = get_workdir(workdir)

        self.stdin_fname = None
        self.stdout_fname, self.stderr_fname = \
            map(os.path.join, 2 * [workdir], ["fold2bloch.stdout", "fold2bloch.stderr"])

        folds = np.array(folds, dtype=np.int).flatten()
        if len(folds) not in (3, 9):
            raise ValueError("Expecting 3 ints or 3x3 matrix but got %s" % (str(folds)))
        fold_arg = ":".join((str(f) for f in folds))
        wfkpath = os.path.abspath(wfkpath)
        if not os.path.isfile(wfkpath):
            raise RuntimeError("WFK file `%s` does not exist in %s" % (wfkpath, workdir))

        # Usage: $ fold2Bloch file_WFK x:y:z (folds)
        retcode = self.execute(workdir, exec_args=[wfkpath, fold_arg])
        if retcode:
            print("stdout:")
            print(self.stdout_data)
            print("stderr:")
            print(self.stderr_data)
            raise RuntimeError("fold2bloch returned %s in %s" % (retcode, workdir))

        filepaths = [f for f in os.listdir(workdir) if f.endswith("_FOLD2BLOCH.nc")]
        if len(filepaths) != 1:
            raise RuntimeError("Cannot find *_FOLD2BLOCH.nc file in: %s" % str(os.listdir(workdir)))

        return os.path.join(workdir, filepaths[0])


class Lruj(ExecWrapper):
    """
    Wraps the lruj Fortran executable.
    """
    _name = "lruj"

    def run(self, nc_paths: list[str], workdir=None) -> int:
        """
        Execute lruj inside directory `workdir` to analyze `nc_paths`.
        """
        workdir = get_workdir(workdir)

        self.stdin_fname = None
        self.stdout_fname, self.stderr_fname = \
            map(os.path.join, 2 * [workdir], ["lruj.stdout", "lruj.stderr"])

        # We work with absolute paths.
        nc_paths = [os.path.abspath(s) for s in list_strings(nc_paths)]

        retcode = self.execute(workdir, exec_args=nc_paths)
        if retcode != 0:
            print("stdout:")
            print(self.stdout_data)
            print("stderr:")
            print(self.stderr_data)
            raise RuntimeError(f"Error while running lruj in {workdir}")

        return retcode


class Abitk(ExecWrapper):
    """
    Wraps the abitk Fortran executable.
    """
    _name = "abitk"

    stdin_fname = None

    def run(self, exec_args: list, workdir=None) -> int:
        """
        Execute abitk inside directory `workdir`.
        """
        workdir = get_workdir(workdir)
        #print("workdir", workdir)

        self.stdout_fname, self.stderr_fname = \
            map(os.path.join, 2 * [workdir], ["abitk.stdout", "abitk.stderr"])

        retcode = self.execute(workdir, exec_args=exec_args)
        if retcode != 0:
            print("stdout:")
            print(self.stdout_data)
            print("stderr:")
            print(self.stderr_data)
            raise RuntimeError(f"Error while running abitk in {workdir}")

        return retcode
