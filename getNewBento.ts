const apiUrl = "https://opbento.edgexhq.tech/api/bento?n=Aman&g=amanbobal&x=stealthbeast30&l=aman-bobal&i=https%3A%2F%2Fi.ibb.co%2FPtm4qCm%2Fvibes-with-you-ea.jpg&p=https%3A%2F%2Fstealthbeast.netlify.app&z=cb566";
interface BentoResponse {
  url: string;
}

const fetchBentoUrl = async (apiUrl: string): Promise<string> => {
  try {
    const response = await fetch(apiUrl);
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const data: BentoResponse = (await response.json()) as BentoResponse;
    return data.url;
  } catch (error) {
    console.error("Error fetching Bento URL:", error);
    throw error;
  }
};

// @ts-ignore
fetchBentoUrl(apiUrl);
