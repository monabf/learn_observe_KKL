# -*- coding: utf-8 -*-

# Import base utils
import copy
import pathlib
import sys

import matplotlib.pyplot as plt
import numpy as np
import torch

# In order to import learn_KKL we need to add the working dir to the system path
working_path = str(pathlib.Path().resolve())
sys.path.append(working_path)

# Import KKL observer
from learn_KKL.system import QuanserQubeServo2

# Plot measured and simulated trajectories of the Quanser Qube

if __name__ == "__main__":
    system = QuanserQubeServo2()
    dt = 0.004
    tsim = (0, 2000 * dt)

    # Experiment
    fileName = 'example_csv_fin4'
    path = 'Data/QQS2_data_diffx0/' + fileName
    exp = np.genfromtxt(path + '.csv', delimiter=',')
    exp = exp[1:2001, 1:-1]
    exp = system.remap_hardware(exp, add_pi_alpha=False)

    # Simulation
    x0 = torch.from_numpy(exp[0])
    tq, simu = system.simulate(x_0=x0, tsim=tsim, dt=dt)
    simu = system.remap(simu)

    # Compare both
    plt.plot(tq, simu[:, 0], 'x', label=r'simulated $\theta$')
    plt.plot(tq, exp[:, 0], 'x', label=r'experimental $\theta$')
    plt.legend()
    plt.savefig(path + '_theta.pdf', bbox_inches="tight")
    plt.show()
    plt.clf()
    plt.close('all')
    plt.plot(tq, simu[:, 1], 'x', label=r'simulated $\alpha$')
    plt.plot(tq, exp[:, 1], 'x', label=r'experimental $\alpha$')
    plt.legend()
    plt.savefig(path + '_alpha.pdf', bbox_inches="tight")
    plt.show()
    plt.clf()
    plt.close('all')
    plt.plot(tq, simu[:, 2], 'x', label=r'simulated $\dot{\theta}$')
    plt.plot(tq, exp[:, 2], 'x', label=r'experimental $\dot{\theta}$')
    plt.legend()
    plt.savefig(path + '_thetadot.pdf', bbox_inches="tight")
    plt.show()
    plt.clf()
    plt.close('all')
    plt.plot(tq, simu[:, 3], 'x', label=r'simulated $\dot{\alpha}$')
    plt.plot(tq, exp[:, 3], 'x', label=r'experimental $\dot{\alpha}$')
    plt.legend()
    plt.savefig(path + '_alphadot.pdf', bbox_inches="tight")
    plt.show()
    plt.clf()
    plt.close('all')
