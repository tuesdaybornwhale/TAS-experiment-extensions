from google import genai
from google.genai import types

# client = genai.Client()
#
# response = client.models.generate_content(
#     model="gemini-2.5-flash",
#     contents="Say hello from Vertex AI in one sentence.",
# )
#
# print(response)
# print(response.text)


client = genai.Client()


def multi_turn_conversation(model: str = "gemini-2.5-flash"):
    """Hold a three-turn conversation with Gemini.

    The running conversation (each user question and the model's previous
    answers) is accumulated in ``contents`` and passed back on every request,
    so prior turns are retained as context for the next question.
    """
    questions = [
        "In one sentence, what is nucleation in physics?",
        "What is a common everyday example of it?",
        "Given what you just said, why does that example count as nucleation?",
    ]

    contents: list[types.Content] = []
    for question in questions:
        # Cache the user question onto the conversation history.
        contents.append(
            types.Content(role="user", parts=[types.Part(text=question)])
        )

        response = client.models.generate_content(
            model=model,
            contents=contents,
        )

        print(f"Q: {question}")
        print(f"A: {response.text}\n")

        # Cache the model's answer so it is included in the next request.
        contents.append(
            types.Content(role="model", parts=[types.Part(text=response.text)])
        )

    return contents


if __name__ == "__main__":
    multi_turn_conversation()