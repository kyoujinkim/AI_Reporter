from typing import List, Dict
from unstructured.documents.elements import (
    Element, Table
)

def chunk_elements(elements: List[Element]) -> Dict[str, List[Element]]:
    """
    Chunking a list of unstructured elements in order to feed into a LLM.

    Args:
        elements (List[Element]): List of unstructured elements.

    Returns:
        List [List[Element]]: lists of elements as values.
    """
    lookback_limit = 2
    chunk_size = 5

    i = 0
    total_result = []
    result = []

    # if elements is Text or Title, or NarrativeText, add to result, until we reach chunk_size. And then add to total_result. And initialize result.
    # if elements is Table, find the previous Title or NarrativeText and add it to result. And add the Table regardless of chunk_size, until non Table element is found. And add some NarrtiveText And then add to total_result. And initialize result.
    while i < len(elements):
        if isinstance(elements[i], Table):
            # if result is not empty, add it to total_result
            if result:
                total_result.append(result)
                result = []

            # Find the previous Title or NarrativeText
            j = i - 1
            while j > i - lookback_limit and j >= 0 and not isinstance(elements[j], Table):
                j -= 1

            while j < i - 1:
                j += 1
                result.append(elements[j])

            # Continue adding Table elements until a non-Table element is found
            while i < len(elements) and isinstance(elements[i], Table):
                result.append(elements[i])
                i += 1

            # Add some NarrativeText if available
            j = i + 1
            while j < i + lookback_limit and j < len(elements) and not isinstance(elements[j], Table):
                result.append(elements[j])
                j += 1

            total_result.append(result)
            result = []
        else:
            result.append(elements[i])
            if len(result) >= chunk_size:
                total_result.append(result)
                result = []
            i += 1

    # If there are any remaining elements in result, add them to total_result
    if result:
        total_result.append(result)

    return total_result