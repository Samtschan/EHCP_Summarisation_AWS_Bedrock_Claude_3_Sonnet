import pprint
import sys
import boto3
import json

CARRIE_ANN = """
I gave him the bill, he told me that he had enough money to pay for the cheddar
cheese omelet, hash browns and orange juice he ordered, but, unfortunately, he didn’t have enough to give
me a tip because he only had ten dollars on him and the bill was $9.96, so he offered me a scratch-off lottery
ticket instead. I was kind of bummed. I really need my tips because Frank, my boss, pays me and the other
waiters so terribly. I figured I’d win maybe five dollars at the most or nothing at the worst. But oh, well, at
least he was a nice customer. Then I scratched the ticket off and I won the whole jackpot. My twelve-year-old
daughter, Lucille, is now going to be able to have that surgery she needs on her kidney and everything is going
to be okay! """

FORMAL = """A rhetorical question is a figure of speech that uses a question to convey a point rather than asking for a response. The answer to a rhetorical question may be clear, yet the questioner asks it to emphasize the point. Rhetorical questions may be a good method for students to start their English speeches. This method of introducing your material might be appealing to the viewers and encourage them to consider how they personally relate to your issue.
When making an instructive or persuasive speech in an English class, statistics can help to strengthen the speaker’s authority and understanding of the subject. To get your point over quickly and create an emotional response, try using an unexpected statistic or fact that will resonate with the audience.
"""


class AWSReportDrafter:
    def __init__(self, prompts_json_filename="EHC_Plan_prompts.json"):
        """
        :param prompts_json_filename:
        """
        self.max_words = 80
        self.word_count_to_token_count = 1.5
        self.max_tokens = 6000  # to allow a whole form to be output for transparency
        self.prompts_json_filename = prompts_json_filename
        self.EHC_Plan_prompts = eval(open(self.prompts_json_filename, "r").read())
        # the above file should have the format:
        """{
            "EHC_Plan_Prompts": {
                "Child_Young_Person_History": {
                    "Prompt": "Generate a detailed history of the child or young person. Include information on their educational background, significant milestones, and any relevant social or family history. Avoid including any personally identifiable information (PII) such as full names, email addresses, or phone numbers. Focus on providing a comprehensive overview of the child's background and development.",
                    "Example_Output": "The child has been enrolled in mainstream education since the age of 5. They have consistently shown an interest in reading and writing, often participating actively in class discussions. The child has a supportive family environment, with parents who are actively involved in their education. Over the years, the child has developed strong friendships and is well-liked by peers. They have participated in various extracurricular activities, including the school's drama club and chess team."
                },
                "Views_Interests_Strengths_Aspirations": {
                    "Prompt": "Describe the views, interests, strengths, and aspirations of the child or young person. Include details about their personal goals, hobbies, and what they enjoy doing in their free time. Highlight their strengths both academically and socially, and any future aspirations they have shared. Ensure the description is positive and encouraging, without including any PII.",
                    "Example_Output": "The child expresses a strong interest in science and aspires to become a scientist in the future. They enjoy conducting experiments and learning about new scientific concepts. In their free time, the child loves playing football and reading mystery novels. Academically, they excel in mathematics and have a natural aptitude for problem-solving. Socially, the child is a confident communicator and often takes on leadership roles in group activities. They aspire to attend university and pursue a degree in chemistry."
                }, etc
                """
        self.possible_topics = list(self.EHC_Plan_prompts["EHC_Plan_Prompts"].keys())
        self.max_token_safety_multiplier = 3
        self.writer_prompt = """
        Below is a structured form that has been filled out. 
        Use this data to perform the task which will be assigned to you below that form.
        Do not say you are responding to a prompt or task. 
        Do not give any pre-amble or introduction to your response.
        Limit your response to {max_words} sentences. 
        Respond in British English.
            <structured form data>
                {structured_form}
            </structured form data>
            <task>
                {task_prompt}
            </task>
            REMEMBER: Respond in British English.
            REMEMBER: Do not say you are responding to a prompt or task. Do not give any pre-amble or introduction to your response.
        """
        self.style_prompt = """Below are two pieces of text: SOURCE and STYLE. 
        Rewrite the SOURCE text in the style of the STYLE text.
        The re-written should contain all of the information from the SOURCE text,
        but none of the information from the TONE text.
        <SOURCE>
        {source}
        </SOURCE>
        <STYLE>
        {style}
        </STYLE>
        """
        self.shrinker_prompt = """

            Reduce the number of words in the below text to be at most {max_words} words,
            and at least {min_words} words. 
            IMPORTANT: do not change the meaning of the text or remove any information:
            <TEXT>
            {text}
            </TEXT>
            REMEMBER: Reduce the number of words in the below text to be at most {max_words} words,
            and at least {min_words} words.

            """
        self.transparency_prompt = """
                Below is an original structured form. 
                Below that is a summary that was generated from the structured form.
                Analyse which parts of the original structured form were definitely utilised
                to generate the summary.
                Rewrite the summary, adding only inline numerical references. 
                Each inline reference should refer to a part of the structured form that was definitely used to generate the summary.
                Additionally rewrite the original structured form, adding only the numerical reference numbers
                that have been used to generate the summary. Include that whole re-write in your response.
                If you are in doubt about whether a part of the structured form was used to generate the summary,
                do not include it in your references.
                    <structured form data>
                        {structured_form}
                    </structured form data>
                    <summary>
                        {task_prompt}
                    </summary>
                    REMEMBER: Rewrite the summary, adding only inline numerical references. 
                Each inline reference should refer to a part of the structured form that was definitely used to generate the summary.
                Additionally rewrite the original structured form, adding only the numerical reference numbers
                that have been used to generate the summary. Include that whole re-write in your response.
                If you are in doubt about whether a part of the structured form was used to generate the summary,
                do not include it in your references.
                    REMEMBER: Do not say you are responding to a prompt or task. Do not give any pre-amble or introduction to your response.
                """

        self.critic_prompt = """Below is a structured form that has been filled out.
        Go through each section of the form. For each section take on a new persona.
        The persona is an expert on the heading of that section.
        Provide feedback for each section's contents as if you were that expert.
        In particular, focus on the quality of the information provided, the relevance to the heading, and any missing or incorrect details.
        <structured form data>
        {structured_form}
        </structured form data>
        REMEMBER: Above is a structured form that has been filled out.
        Go through each section of the form. For each section take on a new persona.
        The persona is an expert on the heading of that section.
        Provide feedback for each section's contents as if you were that expert.
        In particular, focus on the quality of the information provided, the relevance to the heading, and any missing or incorrect details.
        """
        self.bedrock_version = "bedrock-2023-05-31"
        self.model_id = "anthropic.claude-3-sonnet-20240229-v1:0"

    def call_claude(self, prompt: str) -> str:
        """
        Calls Claude with the given prompt
        :param prompt:
        :return: string response
        """
        bedrock_runtime = boto3.client(
            service_name='bedrock-runtime',
            region_name='eu-west-2'
        )
        prompt_config = {
            "anthropic_version": self.bedrock_version,
            "max_tokens": self.max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        }

        body = json.dumps(prompt_config)
        # https://docs.aws.amazon.com/bedrock/latest/userguide/model-ids.html#model-ids-arns
        accept = "application/json"
        content_type = "application/json"

        response = bedrock_runtime.invoke_model(
            body=body, modelId=self.model_id, accept=accept, contentType=content_type
        )

        response_body = json.loads(response.get("body").read())
        result = response_body.get("content")[0].get("text")
        return result

    def generate_section(self, topic: str, input_form: str, style: str) -> str:
        """
        Generates a section of an EHC plan
        :param topic:
        :param input_form:
        :param style:
        :return:
        """
        if topic not in self.possible_topics:
            print(f"Error: {topic} not in {self.possible_topics}")
            return ""
        writing_prompt = self.writer_prompt.format(structured_form=input_form,
                                                   max_words=self.max_words,
                                                   task_prompt=self.EHC_Plan_prompts[
                                                       'EHC_Plan_Prompts'][topic]['Prompt'])
        # style=style)
        print("Generating summary")
        response = self.call_claude(writing_prompt)

        """print("Styling response")
        styling_prompt = self.style_prompt.format(source=response, style=style)
        response_styled = self.call_claude(styling_prompt)
        response = response_styled"""
        if len(response.split()) > self.max_words:
            print("Response too long, shrinking")
            shrinking_prompt = self.shrinker_prompt.format(text=response, max_words=self.max_words,
                                                           min_words=int(self.max_words * 0.8))
            response = self.call_claude(shrinking_prompt)

        return response

    # get claude to estimate how a summary was generated from a full document
    # by passing it the summary and the full document in the same prompt.
    def transparency_insights(self, summary, full_document):
        transparency_prompt = self.transparency_prompt.format(structured_form=full_document,
                                                              task_prompt=summary)
        response = self.call_claude(transparency_prompt)
        return response

    def critique_form_data(self, structured_form):
        response = self.call_claude(self.critic_prompt.format(structured_form=structured_form))
        return response


# Example usage
example_input_form = open("ExampleInput1.txt", "r", encoding='latin-1').read()

ard = AWSReportDrafter()
possible_topics = ard.possible_topics
print(possible_topics)

# for topic in possible_topics:
topic = possible_topics[0]
print(f"topic: {topic}")
# response = ard.generate_section(topic, example_input_form, style=CARRIE_ANN)
response = open(f"ExampleOutput1_{topic}.txt", "r").read()
print(f"Summary {topic}:")
print(response)
# save this response to file
"""with open(f"ExampleOutput1_{topic}.txt", "w") as f:
    f.write(response)"""

print(len(response.split()))
print("\n")

critique = ard.critique_form_data(example_input_form)
print("CRITIC:")
print(critique)
"""insights = ard.transparency_insights(response, example_input_form)
print("INSIGHTS:")
print(insights)
"""