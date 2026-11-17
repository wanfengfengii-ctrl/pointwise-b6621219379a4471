from fractions import Fraction


def difference_variance(left, right):
    if not isinstance(left.variance, Fraction) or not isinstance(right.variance, Fraction):
        raise ValueError("arm variances must be exact")
    if left.variance <= 0 or right.variance <= 0:
        raise ValueError("arm mean variances must be positive")
    return left.variance + right.variance
