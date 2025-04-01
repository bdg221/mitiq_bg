# Copyright (C) Unitary Foundation
#
# This source code is licensed under the GPL license (v3) found in the
# LICENSE file in the root directory of this source tree.

"""Extrapolation methods for Layerwise Richardson Extrapolation (LRE)"""

from functools import wraps
from typing import Any, Callable, Optional, Union

import numpy as np

from mitiq import QPROGRAM, Executor, Observable, QuantumResult
from mitiq.lre.inference import (
    multivariate_richardson_coefficients,
)
from mitiq.lre.multivariate_scaling import (
    multivariate_layer_scaling,
)
from mitiq.zne.scaling import fold_gates_at_random


def construct_circuits(
    circuit: QPROGRAM,
    degree: int,
    fold_multiplier: int,
    folding_method: Callable[
        [QPROGRAM, float], QPROGRAM
    ] = fold_gates_at_random,  # type: ignore [has-type]
    num_chunks: Optional[int] = None,
    scale_method: Callable[
        [
            QPROGRAM,
            int,
            int,
            Optional[int],
            Callable[[QPROGRAM, float], QPROGRAM],
        ],
        list[QPROGRAM],
    ] = multivariate_layer_scaling,
) -> list[QPROGRAM]:
    """Given a circuit, degree, fold_multiplier, folding_method, num_chunks,
       and an optional scale_method with a default of
       multivariate_layer_scaling, outputs a list of circuits that will be used
       in LRE.

    Args:
        circuit: Circuit to be scaled.
        degree: Degree of the multivariate polynomial.
        fold_multiplier: Scaling gap value required for unitary folding which
            is used to generate the scale factor vectors.
        folding_method: Unitary folding method. Default is
            :func:`fold_gates_at_random`.
        num_chunks: Number of desired approximately equal chunks. When the
            number of chunks is the same as the layers in the input circuit,
            the input circuit is unchanged.
        scale_method: Currently, only multivariate_layer_scaling is available

        circuit: The input circuit to execute with ZNE.
        scale_factors: An array of noise scale factors.
        scale_method: The function for scaling the noise.
            A list of built-in functions can be found in
            ``mitiq.lre.multivariate_scaling``.

    Returns:
        The scaled circuits using the scale_method.
    """
    noise_scaled_circuits = scale_method(
        circuit, degree, fold_multiplier, num_chunks, folding_method
    )
    return noise_scaled_circuits


def combine_results(
    results: list[float],
    circuit: QPROGRAM,
    degree: int,
    fold_multiplier: int,
    num_chunks: Optional[int] = None,
) -> float:
    """Computes the error-mitigated expectation value associated to the
    input results from executing the scaled circuits and using the multivariate
    richardson coeffecients, via the application of Layerwise Richardson
    Extrapolation (LRE).

    Args:
        circuit: Circuit to be scaled.
        degree: Degree of the multivariate polynomial.
        fold_multiplier: Scaling gap value required for unitary folding which
            is used to generate the scale factor vectors.
        num_chunks: Number of desired approximately equal chunks. When the
            number of chunks is the same as the layers in the input circuit,
            the input circuit is unchanged.
        results: An array storing the results of running the scaled circuits.

    Returns:
        The expectation value estimated with LRE.
    """
    linear_combination_coeffs = multivariate_richardson_coefficients(
        circuit, degree, fold_multiplier, num_chunks
    )
    return np.dot(results, linear_combination_coeffs)


def execute_with_lre(
    circuit: QPROGRAM,
    executor: Union[Executor, Callable[[QPROGRAM], QuantumResult]],
    degree: int,
    fold_multiplier: int,
    observable: Optional[Observable] = None,
    folding_method: Callable[
        [QPROGRAM, float], QPROGRAM
    ] = fold_gates_at_random,  # type: ignore [has-type]
    num_chunks: Optional[int] = None,
) -> float:
    r"""
    Defines the executor required for Layerwise Richardson
    Extrapolation as defined in :cite:`Russo_2024_LRE`.

    Note that this method only works for the multivariate extrapolation
    methods. It does not allows a user to choose which layers in the input
    circuit will be scaled.

    .. seealso::

        If you would prefer to choose the layers for unitary
        folding, use :func:`mitiq.zne.scaling.layer_scaling.get_layer_folding`
        instead.

    Args:
        circuit: Circuit to be scaled.
        executor: Executes a circuit and returns a `float`
        degree: Degree of the multivariate polynomial.
        fold_multiplier: Scaling gap value required for unitary folding which
            is used to generate the scale factor vectors.
        observable: Observable to compute the expectation value of. If
            ``None``, the ``executor`` must return an expectation value.
            Otherwise, the ``DensityMatrix`` or ``Bitstrings`` returned by
            ``executor`` is used to compute the expectation of the observable.
        folding_method: Unitary folding method. Default is
            :func:`fold_gates_at_random`.
        num_chunks: Number of desired approximately equal chunks. When the
            number of chunks is the same as the layers in the input circuit,
            the input circuit is unchanged.


    Returns:
        Error-mitigated expectation value

    """
    if not isinstance(executor, Executor):
        executor = Executor(executor)

    noise_scaled_circuits = multivariate_layer_scaling(
        circuit, degree, fold_multiplier, num_chunks, folding_method
    )

    linear_combination_coeffs = multivariate_richardson_coefficients(
        circuit, degree, fold_multiplier, num_chunks
    )

    # verify the linear combination coefficients and the calculated expectation
    # values have the same length
    if len(noise_scaled_circuits) != len(  # pragma: no cover
        linear_combination_coeffs
    ):
        raise AssertionError(
            "The number of expectation values are not equal "
            + "to the number of coefficients required for "
            + "multivariate extrapolation."
        )

    lre_exp_values = executor.evaluate(noise_scaled_circuits, observable)

    return np.dot(lre_exp_values, linear_combination_coeffs)


def mitigate_executor(
    executor: Callable[[QPROGRAM], QuantumResult],
    degree: int,
    fold_multiplier: int,
    observable: Optional[Observable] = None,
    folding_method: Callable[
        [Union[Any], float], Union[Any]
    ] = fold_gates_at_random,
    num_chunks: Optional[int] = None,
) -> Callable[[QPROGRAM], float]:
    """Returns a modified version of the input `executor` which is
    error-mitigated with layerwise richardson extrapolation (LRE).

    Args:
        executor: Executes a circuit and returns a `float`.
        degree: Degree of the multivariate polynomial.
        fold_multiplier Scaling gap value required for unitary folding which
            is used to generate the scale factor vectors.
        observable: Observable to compute the expectation value of. If
            ``None``, the ``executor`` must return an expectation value.
            Otherwise, the ``DensityMatrix`` or ``Bitstrings`` returned by
            ``executor`` is used to compute the expectation of the observable.
        folding_method: Unitary folding method. Default is
            :func:`fold_gates_at_random`.
        num_chunks: Number of desired approximately equal chunks. When the
            number of chunks is the same as the layers in the input circuit,
            the input circuit is unchanged.


    Returns:
        Error-mitigated version of the circuit executor.
    """

    executor_obj = Executor(executor)
    if not executor_obj.can_batch:

        @wraps(executor)
        def new_executor(circuit: QPROGRAM) -> float:
            return execute_with_lre(
                circuit,
                executor,
                degree,
                fold_multiplier,
                observable,
                folding_method,
                num_chunks,
            )
    else:

        @wraps(executor)
        def new_executor(circuits: list[QPROGRAM]) -> list[float]:
            return [
                execute_with_lre(
                    circuit,
                    executor,
                    degree,
                    fold_multiplier,
                    observable,
                    folding_method,
                    num_chunks,
                )
                for circuit in circuits
            ]

    return new_executor


def lre_decorator(
    degree: int,
    fold_multiplier: int,
    observable: Optional[Observable] = None,
    folding_method: Callable[
        [QPROGRAM, float], QPROGRAM
    ] = fold_gates_at_random,
    num_chunks: Optional[int] = None,
) -> Callable[
    [Callable[[QPROGRAM], QuantumResult]], Callable[[QPROGRAM], float]
]:
    """Decorator which adds an error-mitigation layer based on
    layerwise richardson extrapolation (LRE).

    Args:
        degree: Degree of the multivariate polynomial.
        fold_multiplier Scaling gap value required for unitary folding which
            is used to generate the scale factor vectors.
        observable: Observable to compute the expectation value of. If
            ``None``, the ``executor`` must return an expectation value.
            Otherwise, the ``DensityMatrix`` or ``Bitstrings`` returned by
            ``executor`` is used to compute the expectation of the observable.
        folding_method: Unitary folding method. Default is
            :func:`fold_gates_at_random`.
        num_chunks: Number of desired approximately equal chunks. When the
            number of chunks is the same as the layers in the input circuit,
            the input circuit is unchanged.



    Returns:
        Error-mitigated decorator.
    """

    def decorator(
        executor: Callable[[QPROGRAM], QuantumResult],
    ) -> Callable[[QPROGRAM], float]:
        return mitigate_executor(
            executor,
            degree,
            fold_multiplier,
            observable,
            folding_method,
            num_chunks,
        )

    return decorator
