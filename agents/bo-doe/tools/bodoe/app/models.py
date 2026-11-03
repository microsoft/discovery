"""Gaussian-process surrogate models with pluggable backends.

Two backends are supported and selected automatically:

* ``"botorch"`` -- BoTorch/GPyTorch ``SingleTaskGP`` fitted on unit-cube inputs
  and standardized outputs. Preferred when ``torch`` is installed. Acquisitions
  are computed by this package from the GP posterior; for BoTorch's own
  Monte-Carlo acquisitions (qLogEI, qLogNEHVI) call BoTorch directly.
* ``"sklearn"`` -- scikit-learn ``GaussianProcessRegressor`` with an ARD Matern
  5/2 kernel plus a white-noise term. Dependency-light fallback that runs
  anywhere; used for analytic acquisitions and ParEGO-style multi-objective BO.

Both backends expose the same :class:`GPSurrogate` interface, so optimizer code
is backend-agnostic.
"""

from __future__ import annotations

import warnings
from typing import Optional

import numpy as np

__all__ = ["GPSurrogate", "fit_gp", "available_backends", "resolve_backend"]


def available_backends() -> list[str]:
    """List usable GP backends on this machine, most capable first."""
    out = []
    try:  # pragma: no cover - depends on the image
        import torch  # noqa: F401
        import botorch  # noqa: F401
        out.append("botorch")
    except Exception:
        pass
    try:
        import sklearn  # noqa: F401
        out.append("sklearn")
    except Exception:
        pass
    return out


def resolve_backend(backend: str = "auto") -> str:
    """Resolve ``"auto"`` to the best installed backend."""
    avail = available_backends()
    if not avail:
        raise RuntimeError("no GP backend available: install botorch or scikit-learn")
    if backend == "auto":
        return avail[0]
    if backend not in avail:
        raise RuntimeError(f"backend '{backend}' unavailable; installed: {avail}")
    return backend


class GPSurrogate:
    """A single-output Gaussian process over the unit cube.

    Inputs are expected in the unit cube (use ``ParameterSpace.to_unit``).
    Outputs are standardized internally and predictions returned in the
    original output units.

    Args:
        backend: ``"auto"``, ``"botorch"`` or ``"sklearn"``.
        noise: Optional fixed observation noise standard deviation. ``None``
            estimates the noise level from the data.
        seed: RNG seed used for restarts / MC sampling.
    """

    def __init__(self, backend: str = "auto", noise: Optional[float] = None,
                 seed: Optional[int] = None):
        self.backend = resolve_backend(backend)
        self.noise = noise
        self.seed = seed
        self._model = None
        self._mu = 0.0
        self._sd = 1.0
        self.X_: Optional[np.ndarray] = None
        self.y_: Optional[np.ndarray] = None

    # ------------------------------------------------------------------ fit
    def fit(self, X: np.ndarray, y: np.ndarray) -> "GPSurrogate":
        """Fit the GP to unit-cube inputs ``X`` and observations ``y``."""
        X = np.atleast_2d(np.asarray(X, dtype=float))
        y = np.asarray(y, dtype=float).ravel()
        if len(X) != len(y):
            raise ValueError("X and y must have the same number of rows")
        self.X_, self.y_ = X, y
        self._mu = float(np.mean(y))
        self._sd = float(np.std(y))
        if self._sd < 1e-12:
            self._sd = 1.0
        z = (y - self._mu) / self._sd
        if self.backend == "botorch":
            self._fit_botorch(X, z)
        else:
            self._fit_sklearn(X, z)
        return self

    def _fit_sklearn(self, X: np.ndarray, z: np.ndarray) -> None:
        from sklearn.gaussian_process import GaussianProcessRegressor
        from sklearn.gaussian_process.kernels import (ConstantKernel, Matern,
                                                      WhiteKernel)
        d = X.shape[1]
        kernel = (ConstantKernel(1.0, (1e-3, 1e3))
                  * Matern(length_scale=np.full(d, 0.3),
                           length_scale_bounds=(1e-2, 1e2), nu=2.5))
        if self.noise is None:
            kernel = kernel + WhiteKernel(1e-4, (1e-8, 1e0))
            alpha = 1e-10
        else:
            alpha = float((self.noise / self._sd) ** 2)
        gp = GaussianProcessRegressor(kernel=kernel, alpha=alpha,
                                      normalize_y=False, n_restarts_optimizer=5,
                                      random_state=self.seed)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            gp.fit(X, z)
        self._model = gp

    def _fit_botorch(self, X: np.ndarray, z: np.ndarray) -> None:  # pragma: no cover
        import torch
        from botorch.fit import fit_gpytorch_mll
        from botorch.models import SingleTaskGP
        from gpytorch.mlls import ExactMarginalLogLikelihood
        if self.seed is not None:
            torch.manual_seed(self.seed)
        tx = torch.as_tensor(X, dtype=torch.double)
        tz = torch.as_tensor(z, dtype=torch.double).unsqueeze(-1)
        # Inputs are already in the unit cube and outputs already standardized
        # by ``fit``, so BoTorch's own transforms are disabled. That keeps the
        # GP's prior mean and covariance in the same space as ``z``, which the
        # closed-form leave-one-out diagnostic relies on.
        kwargs = {"outcome_transform": None, "input_transform": None}
        if self.noise is not None:
            yvar = float((self.noise / self._sd) ** 2)
            kwargs["train_Yvar"] = torch.full_like(tz, max(yvar, 1e-12))
        model = SingleTaskGP(tx, tz, **kwargs)
        mll = ExactMarginalLogLikelihood(model.likelihood, model)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit_gpytorch_mll(mll)
        model.eval()
        self._model = model

    # -------------------------------------------------------------- predict
    def predict(self, X: np.ndarray, return_std: bool = True):
        """Posterior mean (and standard deviation) in original output units."""
        if self._model is None:
            raise RuntimeError("GPSurrogate.fit must be called before predict")
        X = np.atleast_2d(np.asarray(X, dtype=float))
        if self.backend == "botorch":  # pragma: no cover
            import torch
            with torch.no_grad():
                post = self._model.posterior(torch.as_tensor(X, dtype=torch.double))
                mean = post.mean.squeeze(-1).cpu().numpy()
                std = post.variance.clamp_min(1e-12).sqrt().squeeze(-1).cpu().numpy()
        else:
            mean, std = self._model.predict(X, return_std=True)
        mean = mean * self._sd + self._mu
        std = np.asarray(std) * self._sd
        return (mean, std) if return_std else mean

    # ----------------------------------------------------------- diagnostics
    def _train_prior(self):
        """Prior mean vector and noisy covariance at the training inputs (z units)."""
        if self.backend == "botorch":  # pragma: no cover
            import torch
            tx = torch.as_tensor(self.X_, dtype=torch.double)
            m = self._model
            with torch.no_grad():
                mean = m.mean_module(tx).reshape(-1).cpu().numpy()
                K = m.covar_module(tx).to_dense().cpu().numpy()
                noise = m.likelihood.noise.reshape(-1).cpu().numpy()
            K = K + np.diag(np.broadcast_to(noise, (len(K),)))
            return mean, K
        gp = self._model
        K = gp.kernel_(self.X_) + gp.alpha * np.eye(len(self.X_))
        return np.zeros(len(self.X_)), K

    def loo_r2(self) -> float:
        """Leave-one-out :math:`R^2` of the fitted GP.

        Uses the exact closed form for GP leave-one-out predictions with the
        fitted hyperparameters held fixed (Rasmussen & Williams 2006, eq. 5.12):
        the residual for point ``i`` is ``[K^-1 (y - m)]_i / [K^-1]_ii``. Unlike
        in-sample :math:`R^2`, which an interpolating GP pushes towards 1 even
        on pure noise, this measures how well the surrogate predicts points it
        has not seen.
        """
        if self.X_ is None or len(self.X_) < 4:
            return float("nan")
        z = (self.y_ - self._mu) / self._sd
        mean, K = self._train_prior()
        try:
            Kinv = np.linalg.inv(K)
        except np.linalg.LinAlgError:
            Kinv = np.linalg.pinv(K)
        resid_z = (Kinv @ (z - mean)) / np.diag(Kinv)
        ss_res = float(np.sum((resid_z * self._sd) ** 2))
        ss_tot = float(np.sum((self.y_ - self.y_.mean()) ** 2))
        return 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")


def fit_gp(X: np.ndarray, y: np.ndarray, backend: str = "auto",
           noise: Optional[float] = None, seed: Optional[int] = None) -> GPSurrogate:
    """Convenience wrapper: build and fit a :class:`GPSurrogate`."""
    return GPSurrogate(backend=backend, noise=noise, seed=seed).fit(X, y)
