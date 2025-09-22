"use client";

import { Button, Card, CardBody, CardHeader } from "@heroui/react";
import axios from "axios";
import { useState } from "react";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

export default function Home(): JSX.Element {
  const [message, setMessage] = useState<string>("Click the button to contact the backend.");
  const [loading, setLoading] = useState<boolean>(false);

  const fetchGreeting = async (): Promise<void> => {
    setLoading(true);
    try {
      const response = await axios.get(BACKEND_URL, {
        headers: { Accept: "text/html" }
      });
      setMessage(response.data as string);
    } catch (error) {
      setMessage("Unable to reach the backend. Is it running?");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="container">
      <Card shadow="lg">
        <CardHeader className="header">Chat Backend Demo</CardHeader>
        <CardBody className="body">
          <div className="message" dangerouslySetInnerHTML={{ __html: message }} />
          <Button color="primary" onPress={fetchGreeting} isLoading={loading}>
            Say Hello
          </Button>
        </CardBody>
      </Card>
    </main>
  );
}
