.. :Repository: https://github.com/abinit/abipy
.. :Author: Matteo Giantomassi (http://github.com/abinit)

.. list-table::
    :stub-columns: 1
    :widths: 10 90

    * - Package
      - |pypi-version| |download-with-anaconda| |supported-versions|
    * - Continuous Integration
      - |travis-status| |coverage-status|
    * - Documentation
      - |docs-github| |launch-nbviewer| |launch-binder|

About
=====

AbiPy is a python library to analyze the results produced by Abinit_,
an open-source program for the ab-initio calculations of the physical properties of materials
within Density Functional Theory and Many-Body perturbation theory.
It also provides tools to generate input files and workflows to automate
ab-initio calculations and typical convergence studies.
AbiPy is interfaced with pymatgen_ and this allows users to
benefit from the different tools and python objects available in the pymatgen ecosystem.

The official documentation is hosted on `github pages <http://abinit.github.io/abipy>`_.
Check out our `gallery of plotting scripts <http://abinit.github.io/abipy/gallery/index.html>`_
and the `gallery of AbiPy workflows <http://abinit.github.io/abipy/flow_gallery/index.html>`_.

AbiPy can be used in conjunction with matplotlib_, pandas_, scipy_, seaborn_, ipython_ and jupyter_ notebooks
thus providing a powerful and user-friendly environment for data analysis and visualization.

To learn more about the integration between jupyter_ and AbiPy, visit `our collection of notebooks
<https://abinit.github.io/abipy_book/intro.html>`_

AbiPy is free to use. However, we also welcome your help to improve this library by making your own contributions.
Please report any bugs and issues at AbiPy's `Github page <https://github.com/abinit/abipy>`_.

Links to talks
==============

This section collects links to some of the talks given by the AbiPy developers.

* `The new features of AbiPy v0.9.1. 10th international ABINIT developer workshop, May 31 - June 4, 2021 <https://gmatteo.github.io/abipy_abidev2021/#/>`_ (New workflows, plotly interface, etc.)

* `Automating ABINIT calculations with AbiPy. Boston MA, 3 March 2019 <https://gmatteo.github.io/abipy_slides_aps_boston_2019/>`_ (Introduction to AbiPy for newcomers).

* `New features of AbiPy v0.7. Louvain-la-Neuve, Belgium, 20 May 2019 <https://gmatteo.github.io/abipy_intro_abidev2019/>`_ (How to use the AbiPy command line interface in the terminal)

* `Automatize a DFT code: high-throughput workflows for Abinit
  <https://object.cscs.ch/v1/AUTH_b1d80408b3d340db9f03d373bbde5c1e/learn-public/materials/2019_05_aiida_tutorial/day4_abipy_Petretto.pdf>`_


Getting AbiPy
=============

Stable version
--------------

The version at the Python Package Index (PyPI) is always the latest stable release
that can be installed in user mode with::

    pip install abipy --user

Note that you may need to install some optional dependencies manually.
In this case, please consult the detailed installation instructions provided by the
`pymatgen howto <https://pymatgen.org/installation.html>`_ to install pymatgen
and then follow the instructions in `our howto <http://abinit.github.io/abipy/installation>`_.

The installation process is greatly simplified if you install the required
python packages through `Anaconda <https://continuum.io/downloads>`_ (or conda).
See `Installing conda`_ to install conda itself.
We routinely use conda_ to test new developments with multiple Python versions and multiple virtual environments.

Create a new conda_ environment based on python 3.12 (let's call it ``abienv``) with::

    conda create --name abienv python=3.12

and activate it with::

    conda activate abienv

You should see the name of the conda environment in the shell prompt.

Finally, install AbiPy with::

    conda install abipy -c conda-forge --yes

Please note that, it is also possible to install the abinit executables in the same environment using::

    conda install abinit -c conda-forge --yes

Additional information on the steps required to install AbiPy with anaconda are available
in the `anaconda howto <http://abinit.github.io/abipy/installation#anaconda-howto>`_.


Developmental version
---------------------

To install the developmental version of AbiPy with pip, use::

    pip install git+https://github.com/abinit/abipy.git@develop

Clone the `github repository <https://github.com/abinit/abipy>`_ with::

    git clone https://github.com/abinit/abipy

For pip, use::

    pip install -r requirements.txt
    pip install -r requirements-optional.txt

If you are using conda_ (see `Installing conda`_ to install conda itself), create a new environment (``abienv``) with::

    conda create -n abienv python=3.12
    source activate abienv

Add ``conda-forge``, and ``abinit`` to your channels with::

    conda config --add channels conda-forge
    conda config --add channels abinit

and install the AbiPy dependencies with::

    conda install --file ./requirements.txt
    conda install --file ./requirements-optional.txt

The second command is needed for Jupyter only.
Once the requirements have been installed (either with pip or conda), execute::

    python setup.py install

or alternately::

    python setup.py develop

to install the package in developmental mode.
This is the recommended approach, especially if you are planning to implement new features.

Also note that the BLAS/Lapack libraries provided by conda have multithreading support activated by default.
Each process will try to use all of the cores on your machine, which quickly overloads things
if there are multiple processes running.
(Also, this is a shared machine, so it is just rude behavior in general).
To disable multithreading, add these lines to your ~/.bash_profile::

    export OPENBLAS_NUM_THREADS=1
    export OMP_NUM_THREADS=1

and then activate these settings with::

    source ~/.bash_profile

The Github version include test files for complete unit testing.
To run the suite of unit tests, make sure you have pytest_ installed and then type::

    pytest

in the AbiPy root directory. A quicker check might be obtained with::

    pytest abipy/core/tests -v

Unit tests require ``scripttest`` that can be installed with::

    pip install scripttest

Two tests rely on the availability of a
`pymatgen PMG_MAPI_KEY <http://pymatgen.org/usage.html#setting-the-pmg-mapi-key-in-the-config-file>` in ~/.pmgrc.yaml.

Note that several unit tests check the integration between AbiPy and Abinit.
In order to run the tests, you will need a working set of Abinit executables and  a ``manager.yml`` configuration file.

Contributing to AbiPy is relatively easy.
Just send us a `pull request <https://help.github.com/articles/using-pull-requests/>`_.
When you send your request, make ``develop`` the destination branch on the repository
AbiPy uses the `Git Flow <http://nvie.com/posts/a-successful-git-branching-model/>`_ branching model.
The ``develop`` branch contains the latest contributions, and ``master`` is always tagged and points
to the latest stable release.

Installing without internet access
----------------------------------

Here, it is described how to set up a virtual environment with AbiPy on a cluster that cannot reach out to the internet.
One first creates a virtual environment with AbiPy on a cluster/computer with access, then ports the required files to the cluster without access, and performs an offline installation.
We use Conda for the Python installation and pip for the packages, as the former reduces the odds that incompatibilities arise, while the latter provides convenient syntax for offline package installation.

One first needs Conda on the cluster with access.
If not available by default, follow the instructions for installing Conda at the bottom of this page.
Next, set up a conda virtual environment with a designated Python version, for example 3.12::

    conda create --name abienv python=3.12
    conda activate abienv

We then install AbiPy in this virtual environment, followed by creating requirements.txt, and creating a folder packages/ containing all the wheels (.whl format)::

    pip install abipy
    pip list --format=freeze > requirements.txt
    pip download -r requirements.txt -d packages/

Next, the .txt file, the folder, and the miniconda installer must be forwarded to the cluster without internet access.
You may have to use a computer that has access to both locations with the scp command.
If the offline cluster does not have Conda preinstalled, the Miniconda executable must be ported so that an offline Conda installation can be performed.
Thus, from a computer that can access both locations, execute::

    scp -r connected_cluster:/file/and/folder/location/* .
    wget https://repo.continuum.io/miniconda/Miniconda3-latest-Linux-x86_64.sh
    scp -r requirements.txt packages/ Miniconda3-latest-Linux-x86_64.sh disconnected_cluster:/desired/location/

If conda is not available on the cluster that cannot access the internet, follow the instructions on the bottom of this page to install it.
Next, one can set up an **offline** virtual environment on the cluster without internet access::

    conda create --name abienv --offline python=3.12
    conda activate abienv

At this step, AbiPy might fail to install due to missing/incompatible packages.
Some of these issues may be solved by repeating the above steps (excluding the environment creation) for packages that are listed as missing/incompatible during the installation procedure, by updating the requirements.txt and packages/ and trying to install again.
Upon reading::

	Successfully installed abipy-x.y.z

You can quickly test your installation by running ``python`` followed by ``import abipy``.

Installing Abinit
=================

One of the big advantages of conda over pip is that conda can also install libraries and executables written in Fortran.
A pre-compiled sequential version of Abinit for Linux and OSx can be installed directly from the
conda-forge channel with::

    conda install abinit -c conda-forge

Otherwise, follow the usual abinit installation instructions, and make sure abinit can be run with the command::

    abinit --version

Configuration files for Abipy
=============================

In order to run the Abipy tests, you will need a ``manager.yml`` configuration file.
For a detailed description of the syntax used in this configuration file
please consult the `TaskManager documentation <http://abinit.github.io/abipy/workflows/taskmanager.html>`_.

At this stage, for the purpose of checking the installation, you might
take the ``shell_nompi_manager.yml`` file from the ``abipy/data/managers`` directory
of this repository, and copy it with new name ``manager.yml`` to your `$HOME/.abinit/abipy` directory.
Open this file and make sure that the ``pre_run`` section contains the shell commands
needed to setup the environment before launching Abinit (e.g. Abinit is in $PATH), unless it is available from the environment (e.g. conda).

To complete the configuration files for Abipy, you might also copy the ``simple_scheduler.yml`` file from the same directory,
and copy it with name ``scheduler.yml``. Modifications are needed if you are developer.

Checking the installation
=========================

Now open the python interpreter and import the following three modules
to check that the python installation is OK::

    import spglib
    import pymatgen
    from abipy import abilab

then quit the interpreter.

For general information about how to troubleshoot problems that may occur at this level,
see the :ref:`troubleshooting` section.

.. _anaconda_howto:

The Abinit executables are placed inside the anaconda directory associated to the ``abienv`` environment::

    which abinit
    /Users/gmatteo/anaconda3/envs/abienv/bin/abinit

To perform a basic validation of the build, execute::

    abinit -b

Abinit should echo miscellaneous information, starting with::

    DATA TYPE INFORMATION:
    REAL:      Data type name: REAL(DP)
               Kind value:      8
               Precision:      15

and ending with::

    ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
    Default optimizations:
      --- None ---


    ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

If successful, one can start to use the AbiPy scripts from the command line to analyze the output results.
Execute::

    abicheck.py

You should see (with minor changes)::

    $ abicheck.py
    AbiPy Manager:
    [Qadapter 0]
    ShellAdapter:localhost
    Hardware:
       num_nodes: 2, sockets_per_node: 1, cores_per_socket: 2, mem_per_node 4096,
    Qadapter selected: 0

    Abinitbuild:
    Abinit Build Information:
        Abinit version: 8.8.2
        MPI: True, MPI-IO: True, OpenMP: False
        Netcdf: True

    Abipy Scheduler:
    PyFlowScheduler, Pid: 19379
    Scheduler options: {'weeks': 0, 'days': 0, 'hours': 0, 'minutes': 0, 'seconds': 5}

    Installed packages:
    Package         Version
    --------------  ---------
    system          Darwin
    python_version  3.6.5
    numpy           1.14.3
    scipy           1.1.0
    netCDF4         1.4.0
    apscheduler     2.1.0
    pydispatch      2.0.5
    yaml            3.12
    pymatgen        2018.6.11


    Abipy requirements are properly configured

If the script fails with the error message::

    Abinit executable does not support netcdf
    Abipy requires Abinit version >= 8.0.8 but got 0.0.0

it means that your environment is not property configured or that there's a problem with the binary executable.
In this case, look at the files produced in the temporary directory of the flow.
The script reports the name of the directory, something like::

    CRITICAL:pymatgen.io.abinit.tasks:Error while executing /var/folders/89/47k8wfdj11x035svqf8qnl4m0000gn/T/tmp28xi4dy1/job.sh

Check the `job.sh` script for possible typos, then search for possible error messages in `run.err`.

The last test consists in executing a small calculation with AbiPy and Abinit.
Inside the terminal, execute::

    abicheck.py --with-flow

to run a GS + NSCF band structure calculation for Si.
If the software stack is properly configured, the output should end with::

    Work #0: <BandStructureWork, node_id=313436, workdir=../../../../var/folders/89/47k8wfdj11x035svqf8qnl4m0000gn/T/tmpygixwf9a/w0>, Finalized=True
      Finalized works are not shown. Use verbose > 0 to force output.

    all_ok reached

    Submitted on: Sat Jul 28 09:14:28 2018
    Completed on: Sat Jul 28 09:14:38 2018
    Elapsed time: 0:00:10.030767
    Flow completed successfully

    Calling flow.finalize()...

    Work #0: <BandStructureWork, node_id=313436, workdir=../../../../var/folders/89/47k8wfdj11x035svqf8qnl4m0000gn/T/tmpygixwf9a/w0>, Finalized=True
      Finalized works are not shown. Use verbose > 0 to force output.

    all_ok reached


    Test flow completed successfully

Great, if you've reached this part it means that you've installed AbiPy and Abinit on your machine!
We can finally start to run the scripts in this repo or use one of the AbiPy script to analyze  the results.


Using AbiPy
===========

Basic usage
-----------

There are a variety of ways to use AbiPy, and most of them are illustrated in the ``abipy/examples`` directory.
Below is a brief description of the different directories found there:

  * `examples/plot <http://abinit.github.io/abipy/gallery/index.html>`_

    Scripts showing how to read data from netcdf files and produce plots with matplotlib_

  * `examples/flows <http://abinit.github.io/abipy/flow_gallery/index.html>`_.

    Scripts showing how to generate an AbiPy flow, run the calculation and use ipython to analyze the data.

Additional jupyter notebooks with the Abinit tutorials written with AbiPy are available in the
`abitutorial repository <https://nbviewer.jupyter.org/github/abinit/abitutorials/blob/master/abitutorials/index.ipynb>`_.

Users are strongly encouraged to explore the detailed `API docs <http://abinit.github.io/abipy/api/index.html>`_.

Command line tools
------------------

The following scripts can be invoked directly from the terminal:

* ``abiopen.py``    Open file inside ipython.
* ``abistruct.py``  Swiss knife to operate on structures.
* ``abiview.py``    Visualize results from file.
* ``abicomp.py``    Compare results extracted from multiple files.
* ``abicheck.py``   Validate integration between AbiPy and Abinit
* ``abirun.py``     Execute AbiPy flow from terminal.
* ``abidoc.py``     Document Abinit input variables and Abipy configuration files.
* ``abinp.py``      Build input files (simplified interface for the AbiPy factory functions).
* ``abipsp.py``     Download pseudopotential tables from the PseudoDojo.

Use ``SCRIPT --help`` to get the list of supported commands and
``SCRIPT COMMAND --help`` to get the documentation for ``COMMAND``.

For further information, please consult the `scripts docs <http://abinit.github.io/abipy/scripts/index.html>`_ section.


Installing conda
================

A brief install guide, in case you have not yet used conda ... For a more extensive description, see our
`Anaconda Howto <http://abinit.github.io/abipy/installation#anaconda-howto>`_.

Download the `miniconda installer <https://conda.io/miniconda.html>`_.
Select the version corresponding to your operating system.

As an example, if you are a Linux user, download and install `miniconda` on your local machine with::

    wget https://repo.continuum.io/miniconda/Miniconda3-latest-Linux-x86_64.sh
    bash Miniconda3-latest-Linux-x86_64.sh

while for MacOSx use::

    curl -o https://repo.continuum.io/miniconda/Miniconda3-latest-MacOSX-x86_64.sh
    bash Miniconda3-latest-MacOSX-x86_64.sh

Answer ``yes`` to the question::

    Do you wish the installer to prepend the Miniconda3 install location
    to PATH in your /home/gmatteo/.bashrc ? [yes|no]
    [no] >>> yes

Source your ``.bashrc`` file to activate the changes done by ``miniconda`` to your ``$PATH``::

    source ~/.bashrc

.. _troubleshooting:

License
=======

AbiPy is released under the GNU GPL license. For more details see the LICENSE file.

.. _Python: http://www.python.org/
.. _Abinit: https://www.abinit.org
.. _abinit-channel: https://anaconda.org/abinit
.. _pymatgen: http://pymatgen.org
.. _matplotlib: http://matplotlib.org
.. _pandas: http://pandas.pydata.org
.. _scipy: https://www.scipy.org/
.. _seaborn: https://seaborn.pydata.org/
.. _ipython: https://ipython.org/index.html
.. _jupyter: http://jupyter.org/
.. _netcdf: https://www.unidata.ucar.edu/software/netcdf/docs/faq.html#whatisit
.. _abiconfig: https://github.com/abinit/abiconfig
.. _conda: https://conda.io/docs/
.. _netcdf4-python: http://unidata.github.io/netcdf4-python/
.. _spack: https://github.com/LLNL/spack
.. _pytest: https://docs.pytest.org/en/latest/contents.html
.. _numpy: http://www.numpy.org/


.. |pypi-version| image:: https://badge.fury.io/py/abipy.svg
    :alt: PyPi version
    :target: https://badge.fury.io/py/abipy

.. |travis-status| image:: https://travis-ci.org/abinit/abipy.svg?branch=develop
    :alt: Travis status
    :target: https://travis-ci.org/abinit/abipy

.. |coverage-status| image:: https://coveralls.io/repos/github/abinit/abipy/badge.svg?branch=develop
    :alt: Coverage status
    :target: https://coveralls.io/github/abinit/abipy?branch=develop

.. |download-with-anaconda| image:: https://anaconda.org/abinit/abipy/badges/installer/conda.svg
    :alt: Download with Anaconda
    :target: https://anaconda.org/conda-forge/abinit

.. |launch-binder| image:: https://mybinder.org/badge.svg
    :alt: Launch binder
    :target: https://mybinder.org/v2/gh/abinit/abipy/develop

.. |launch-nbviewer| image:: https://img.shields.io/badge/render-nbviewer-orange.svg
    :alt: Launch nbviewer
    :target: https://nbviewer.jupyter.org/github/abinit/abitutorials/blob/master/abitutorials/index.ipynb

.. |supported-versions| image:: https://img.shields.io/pypi/pyversions/abipy.svg?style=flat
    :alt: Supported versions
    :target: https://pypi.python.org/pypi/abipy

.. |requires| image:: https://requires.io/github/abinit/abipy/requirements.svg?branch=develop
     :target: https://requires.io/github/abinit/abipy/requirements/?branch=develop
     :alt: Requirements Status

.. |docs-github| image:: https://img.shields.io/badge/docs-ff69b4.svg
     :alt: AbiPy Documentation
     :target: http://abinit.github.io/abipy
