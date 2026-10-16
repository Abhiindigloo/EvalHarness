import OpenAI from "openai";
const client = new OpenAI();
export const draft = (t: string) => client.responses.create({ model: "gpt-4.1-mini", input: t });
export const final = (t: string) => client.responses.create({ model: "gpt-4.1-mini", input: t });
