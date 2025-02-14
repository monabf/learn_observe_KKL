# -*- coding: utf-8 -*-

import os
import pathlib
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sb
# Import base utils
import torch
from torch import nn
from functorch import vmap, jacfwd, jacrev

# To avoid Type 3 fonts for submission https://tex.stackexchange.com/questions/18687/how-to-generate-pdf-without-any-type3-fonts
# https://jwalton.info/Matplotlib-latex-PGF/
# https://stackoverflow.com/questions/12322738/how-do-i-change-the-axis-tick-font-in-a-matplotlib-plot-when-rendering-using-lat
sb.set_style('whitegrid')
plot_params = {
    'font.family': 'serif',
    'text.usetex': True,
    'pgf.rcfonts': False,
    'font.serif': 'Palatino',
    'font.size': 16,
    "pgf.preamble": "\n".join([
        r'\usepackage{bm}',
    ]),
    'text.latex.preamble': [r'\usepackage{amsmath}',
                            r'\usepackage{amssymb}',
                            r'\usepackage{cmbright}'],
}
plt.rcParams.update(plot_params)

# In order to import learn_KKL we need to add the working dir to the system path
working_path = str(pathlib.Path().resolve())
sys.path.append(working_path)

# Import KKL observer
from learn_KKL.learner import Learner
from learn_KKL.system import RevDuffing
from learn_KKL.luenberger_observer import LuenbergerObserver

# Import learner utils
import pytorch_lightning as pl
from pytorch_lightning.callbacks import ModelCheckpoint
from pytorch_lightning.loggers import TensorBoardLogger
from sklearn.model_selection import train_test_split
import torch.optim as optim

if __name__ == "__main__":

    TRAIN = True

    ##########################################################################
    # Setup observer #########################################################
    ##########################################################################

    # Learning method
    learning_method = "Supervised"
    num_hl = 5
    size_hl = 50
    activation = nn.SiLU()

    # Define system
    system = RevDuffing()

    # Define data params
    wc = 0.15
    x_limits = np.array([[-1., 1.], [-1., 1.]])
    num_samples = 10000

    # Solver options
    solver_options = {'method': 'rk4', 'options': {'step_size': 1e-3}}

    if TRAIN:
        # Instantiate observer object
        observer = LuenbergerObserver(
            dim_x=system.dim_x,
            dim_y=system.dim_y,
            method=learning_method,
            wc=wc,
            activation=activation,
            num_hl=num_hl,
            size_hl=size_hl,
            solver_options=solver_options,
        )
        observer.set_dynamics(system)

        # Generate training data and validation data
        data = observer.generate_data_svl(x_limits, num_samples, method="LHS",
                                          k=10)
        data, val_data = train_test_split(data, test_size=0.3, shuffle=True)

        ##########################################################################
        # Setup learner ##########################################################
        ##########################################################################

        # Trainer options
        num_epochs = 100
        trainer_options = {"max_epochs": num_epochs}
        batch_size = 100
        init_learning_rate = 5e-3

        # Optim options
        optim_method = optim.Adam
        optimizer_options = {"weight_decay": 1e-8}

        # Scheduler/stopper options
        scheduler_method = optim.lr_scheduler.ReduceLROnPlateau
        scheduler_options = {
            "mode": "min",
            "factor": 0.1,
            "patience": 5,
            "threshold": 1e-4,
            "verbose": True,
        }
        stopper = pl.callbacks.early_stopping.EarlyStopping(
            monitor="val_loss", min_delta=1e-4, patience=10, verbose=False,
            mode="min"
        )

        # Instantiate learner for T
        learner_T = Learner(
            observer=observer,
            system=system,
            training_data=data,
            validation_data=val_data,
            method='T',
            batch_size=batch_size,
            lr=init_learning_rate,
            optimizer=optim_method,
            optimizer_options=optimizer_options,
            scheduler=scheduler_method,
            scheduler_options=scheduler_options,
        )

        # Define logger and checkpointing
        logger = TensorBoardLogger(
            save_dir=learner_T.results_folder + '/tb_logs')
        checkpoint_callback = ModelCheckpoint(monitor='val_loss')
        trainer = pl.Trainer(
            callbacks=[stopper, checkpoint_callback],
            **trainer_options,
            logger=logger,
            log_every_n_steps=1,
            check_val_every_n_epoch=3
        )

        # To see logger in tensorboard, copy the following output name_of_folder
        print(f"Logs stored in {learner_T.results_folder}/tb_logs")

        # Train the transformation function using the learner class
        trainer.fit(learner_T)

        ##########################################################################
        # Generate plots #########################################################
        ##########################################################################

        learner_T.save_results(limits=x_limits, nb_trajs=10, tsim=(0, 50),
                               dt=1e-2,
                               checkpoint_path=checkpoint_callback.best_model_path)

        # Scheduler/stopper options
        scheduler_method = optim.lr_scheduler.ReduceLROnPlateau
        scheduler_options = {
            "mode": "min",
            "factor": 0.1,
            "patience": 3,
            "threshold": 1e-4,
            "verbose": True,
        }
        stopper = pl.callbacks.early_stopping.EarlyStopping(
            monitor="val_loss", min_delta=1e-4, patience=10, verbose=False,
            mode="min"
        )

        # Instantiate learner for T_star
        learner_T_star = Learner(
            observer=observer,
            system=system,
            training_data=data,
            validation_data=val_data,
            method="T_star",
            batch_size=batch_size,
            lr=init_learning_rate,
            optimizer=optim_method,
            optimizer_options=optimizer_options,
            scheduler=scheduler_method,
            scheduler_options=scheduler_options,
        )

        # Define logger and checkpointing
        logger = TensorBoardLogger(
            save_dir=learner_T_star.results_folder + "/tb_logs")
        checkpoint_callback = ModelCheckpoint(monitor="val_loss")
        trainer = pl.Trainer(
            callbacks=[stopper, checkpoint_callback],
            **trainer_options,
            logger=logger,
            log_every_n_steps=1,
            check_val_every_n_epoch=3,
        )

        # To see logger in tensorboard, copy the following output name_of_folder
        print(f"Logs stored in {learner_T_star.results_folder}/tb_logs")

        # Train the transformation function using the learner class
        trainer.fit(learner_T_star)

    else:
        # Load learner
        path = "runs/Reversed_Duffing_Oscillator/Supervised/T_star" \
               "/N1e4_wc075_correcteddyns"
        learner_path = path + "/learner.pkl"
        import dill as pkl

        with open(learner_path, "rb") as rb_file:
            learner_T_star = pkl.load(rb_file)
        learner_T_star.results_folder = path
        observer = learner_T_star.model
        verbose = False
        gradient_plots = False
        save = True
        correct_dyns = True

    ##########################################################################
    # Generate plots #########################################################
    ##########################################################################

    learner_T_star.save_results(
        limits=x_limits, nb_trajs=10, tsim=(0, 50), dt=1e-2,
        checkpoint_path=checkpoint_callback.best_model_path)

    # Plot heatmaps of transformations and their gradients
    if gradient_plots:
        # Corrected dynamics
        if correct_dyns:
            from torchdiffeq import odeint
            def simulate(y: torch.tensor, tsim: tuple, dt: float, z_0=None) -> \
                    torch.tensor:
                self = learner_T_star.model
                # Output timestemps of solver
                tq = torch.arange(tsim[0], tsim[1], dt)
                # 1D interpolation of y
                measurement = self.interpolate_func(y)
                # Zero initial value
                if z_0 is None:
                    z_0 = torch.zeros((1, self.dim_z))

                def dydt(t, z: torch.tensor):
                    xhat = self.decoder(z)
                    zhat = self.encoder(xhat)
                    dTdx = vmap(jacfwd(self.encoder))(xhat)
                    lhs = torch.einsum("ijk,ik->ij", dTdx, self.f(xhat))
                    rhs = torch.matmul(
                        zhat, self.D.t()) + torch.matmul(self.h(xhat),
                                                         self.F.t())
                    z_dot = torch.matmul(z, self.D.t()) + torch.matmul(
                        measurement(t), self.F.t()) + (lhs - rhs)
                    # test = (torch.matmul(self.D, z.t()) + torch.matmul(
                    #     self.F, measurement(t).t()) + torch.matmul(
                    #     torch.squeeze(dTdx), self.f(xhat).t()) -
                    #          torch.matmul(self.D, self.encoder(xhat).t()) -
                    #          torch.matmul(self.F, self.h(xhat).t())).t()
                    return z_dot

                # Solve
                print('new simulate')
                z = odeint(dydt, z_0, tq, **self.solver_options)
                return tq, z


            learner_T_star.model.simulate = simulate
            # learner_T_star.save_results(
            #     limits=x_limits, nb_trajs=10, tsim=(0, 50), dt=1e-2)
            traj_folder = os.path.join(path, 'Test_trajectories')
            learner_T_star.save_random_traj(x_mesh=None, num_samples=10000,
                                     nb_trajs=10,
                                     verbose=verbose, tsim=(0, 50), dt=1e-2,
                                     std=0.,
                                     traj_folder=traj_folder)

        if save:
            # Gradient heatmap computed numerically
            # Need true regular grid in x, i.e. num_per_dim ** dim_x = num_samples!
            mesh = learner_T_star.model.generate_data_svl(x_limits, 10000,
                                                   method='uniform')
            x = mesh[:, learner_T_star.x_idx_in]
            z = mesh[:, learner_T_star.z_idx_in]
            path = os.path.join(learner_T_star.results_folder, 'gradients')
            os.makedirs(path, exist_ok=False)
            file = pd.DataFrame(mesh)
            file.to_csv(os.path.join(path, f'mesh.csv'), header=False)
            T = learner_T_star.model.encoder(x)
            Tstar = learner_T_star.model.decoder(z)

            # Gradient heatmap of NN model
            dTdx = vmap(jacfwd(learner_T_star.model.encoder))(x)
            dTdx = dTdx[:, :, : learner_T_star.model.dim_x]
            idx_max = torch.argmax(torch.linalg.matrix_norm(dTdx, ord=2))
            Tmax = dTdx[idx_max]
            # Compute dTstar_dz over grid
            dTstar_dz = vmap(jacrev(learner_T_star.model.decoder))(z)
            dTstar_dz = dTstar_dz[:, :, : learner_T_star.model.dim_z]
            idxstar_max = torch.argmax(
                torch.linalg.matrix_norm(dTstar_dz, ord=2))
            Tstar_max = dTstar_dz[idxstar_max]
            # Save this data
            # import pandas as pd
            # import os
            # path = os.path.join(learner_T_star.results_folder, 'gradients')
            # os.makedirs(path, exist_ok=True)
            file = pd.DataFrame(Tmax)
            file.to_csv(os.path.join(path, f'Tmax.csv'), header=False)
            file = pd.DataFrame(Tstar_max)
            file.to_csv(os.path.join(path, f'Tstar_max.csv'), header=False)
            file = pd.DataFrame(dTdx.flatten(1, -1))
            file.to_csv(os.path.join(path, f'dTdx.csv'), header=False)
            file = pd.DataFrame(dTstar_dz.flatten(1, -1))
            file.to_csv(os.path.join(path, f'dTstar_dz.csv'), header=False)

        else:
            # Saved
            path = os.path.join(learner_T_star.results_folder, 'gradients')
            df = pd.read_csv(os.path.join(path, f'mesh.csv'), sep=',',
                             header=None)
            mesh = torch.from_numpy(df.drop(df.columns[0], axis=1).values)
            df = pd.read_csv(os.path.join(path, f'Tmax.csv'), sep=',',
                             header=None)
            Tmax = torch.from_numpy(df.drop(df.columns[0], axis=1).values)
            df = pd.read_csv(os.path.join(path, f'dTdx.csv'), sep=',',
                             header=None)
            dTdx = torch.from_numpy(
                df.drop(df.columns[0], axis=1).values).reshape(
                (-1, Tmax.shape[0], Tmax.shape[1]))
            df = pd.read_csv(os.path.join(path, f'Tstar_max.csv'), sep=',',
                             header=None)
            Tstar_max = torch.from_numpy(df.drop(df.columns[0], axis=1).values)
            df = pd.read_csv(os.path.join(path, f'dTstar_dz.csv'), sep=',',
                             header=None)
            dTstar_dz = torch.from_numpy(
                df.drop(df.columns[0], axis=1).values).reshape(
                (-1, Tstar_max.shape[0], Tstar_max.shape[1]))

        # Plots
        plt.rcParams['axes.grid'] = False
        x = mesh[:, learner_T_star.x_idx_in]
        z = mesh[:, learner_T_star.z_idx_in]
        with torch.no_grad():
            T = learner_T_star.model.encoder(x)
            Tstar = learner_T_star.model.decoder(z)
        # Plot T and its gradients over grid of x
        for i in range(len(learner_T_star.x_idx_in) - 1):
            for j in range(len(learner_T_star.z_idx_out)):
                name = f'T{j}_{i}.pdf'
                plt.scatter(x[:, i], x[:, i + 1], cmap="jet", c=T[:, j])
                m = torch.max(torch.abs(T[:, j]))
                plt.clim(-m, m)
                plt.colorbar()
                plt.xlabel(rf'$x_{i + 1}$')
                plt.ylabel(rf'$x_{i + 2}$')
                plt.title(rf'$T_{j + 1}(x)$')
                plt.savefig(os.path.join(path, name), bbox_inches="tight")
                if verbose:
                    plt.show()
                plt.clf()
                plt.close('all')

                for k in range(len(learner_T_star.x_idx_in)):
                    name = f'dT{j}dx{k}_{i}.pdf'
                    plt.scatter(x[:, i], x[:, i + 1], cmap="jet",
                                c=dTdx[:, j, k])
                    m = torch.max(torch.abs(dTdx[:, j, k]))
                    plt.clim(-m, m)
                    plt.colorbar()
                    plt.xlabel(rf'$x_{i + 1}$')
                    plt.ylabel(rf'$x_{i + 2}$')
                    plt.title(
                        rf'$\frac{{\partial T_{j + 1}}}{{\partial x_{k + 1}}}(x)$')
                    plt.savefig(os.path.join(path, name), bbox_inches="tight")
                    if verbose:
                        plt.show()
                    plt.clf()
                    plt.close('all')
        # Plot Tstar and its gradients over grid of z
        for i in range(len(learner_T_star.z_idx_in) - 1):
            for j in range(len(learner_T_star.x_idx_out)):
                name = f'Tstar{j}_{i}.pdf'
                plt.scatter(z[:, i], z[:, i + 1], cmap="jet", c=Tstar[:, j])
                m = torch.max(torch.abs(Tstar[:, j]))
                plt.clim(-m, m)
                plt.colorbar()
                plt.xlabel(rf'$z_{i + 1}$')
                plt.ylabel(rf'$z_{i + 2}$')
                plt.title(rf'$T^*_{j + 1}(z)$')
                plt.savefig(os.path.join(path, name), bbox_inches="tight")
                if verbose:
                    plt.show()
                plt.clf()
                plt.close('all')

                for k in range(len(learner_T_star.z_idx_in)):
                    name = f'dTstar{j}dz{k}_{i}.pdf'
                    plt.scatter(z[:, i], z[:, i + 1], cmap="jet",
                                c=dTstar_dz[:, j, k])
                    m = torch.max(torch.abs(dTstar_dz[:, j, k]))
                    plt.clim(-m, m)
                    plt.colorbar()
                    plt.xlabel(rf'$z_{i + 1}$')
                    plt.ylabel(rf'$z_{i + 2}$')
                    plt.title(rf'$\frac{{\partial T^*_{j + 1}}}{{\partial z_'
                              rf'{k + 1}}}(z)$')
                    plt.savefig(os.path.join(path, name), bbox_inches="tight")
                    if verbose:
                        plt.show()
                    plt.clf()
                    plt.close('all')
