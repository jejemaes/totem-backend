import typing as t

NON_FIELD_ERRORS = "__all__"


class ServiceValidationError(Exception):
    def __init__(self, message: t.Union[str, t.List[str], t.Dict[str, t.Union[str, t.List[str]]]], key: t.Optional[str]=None):
        super().__init__(message, key)

        if isinstance(message, dict):
            for k, v in message.items():
                if isinstance(v, str):
                    message[k] = [v]
            self._message_dict = message
        else:
            messages = message
            if isinstance(message, str):
                messages = [message] 

            if key is None:
                key = NON_FIELD_ERRORS
            
            self._message_dict = {key: messages}

    def add_message(self, message: t.Union[str, t.List[str]], key: t.Optional[str]=None):
        if key is None:
            key = NON_FIELD_ERRORS

        if key not in self._message_dict:
            self._message_dict[key] = []

        if isinstance(message, str):
            self._message_dict[key].append(message)
        else:
            self._message_dict[key].extend(message)
    
    def __bool__(self):
        return bool(self._message_dict)
    
    @property
    def message_dict(self):
        return self._message_dict


class RelationNotFound(ServiceValidationError):
    """A relation value does not exist, or is not visible to the acting user.

    Deliberately does not distinguish the two, and its message must not either:
    telling them apart would leak the existence of records outside the caller's
    scope. Being a `ServiceValidationError` it aggregates like any field error.
    """


class ServiceValidationMultiError(Exception):
    def __init__(self, errors: t.Dict[t.Union[str, int], t.Union[t.List[str], ServiceValidationError]], code: t.Optional[str]=None):
        super().__init__(errors, code)
        self._errors = errors
        self.code = code
    
    def add_error(self, key: t.Union[str, int], error: ServiceValidationError):
        self._errors[key] = error

    def __bool__(self):
        return bool(self._errors)

    @property
    def errors(self):
        return self._errors
    
    def dict(self):
        values = {}
        for k, v in self._errors.items():
            if isinstance(v, ServiceValidationError):
                values[k] = v.message_dict
            else:
                values[k] = v
        return values