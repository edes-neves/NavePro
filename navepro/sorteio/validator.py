

class ValidationError(Exception):
    pass


class Validator:

    @staticmethod
    def validate_range(start: str | None, end: str | None) -> tuple[int, int]:
        errors: list[str] = []

        if not start or not start.strip():
            errors.append("Número inicial é obrigatório.")

        if not end or not end.strip():
            errors.append("Número final é obrigatório.")

        if errors:
            raise ValidationError(" ".join(errors))

        start_str = start.strip()
        end_str = end.strip()

        if not start_str.lstrip("-").isdigit():
            errors.append("Número inicial deve ser um valor numérico inteiro.")

        if not end_str.lstrip("-").isdigit():
            errors.append("Número final deve ser um valor numérico inteiro.")

        if errors:
            raise ValidationError(" ".join(errors))

        start_num = int(start_str)
        end_num = int(end_str)

        if start_num > end_num:
            raise ValidationError(
                "O número inicial não pode ser maior que o número final."
            )

        range_size = end_num - start_num + 1
        if range_size < 2:
            raise ValidationError(
                "O intervalo deve conter pelo menos 2 números."
            )

        if range_size > 1_000_000:
            raise ValidationError(
                "Intervalo muito grande. Máximo permitido: 1.000.000 números."
            )

        return start_num, end_num
