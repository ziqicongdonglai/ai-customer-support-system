import type {
    StreamEvent,
    ChatRequest,
} from "@/types/chat";


const API_BASE_URL =
    process.env.NEXT_PUBLIC_API_URL;


function isStreamEventType(
        value: string | undefined,
    ): value is StreamEvent["type"] {
        return (
            value === "start" ||
            value === "sources" ||
            value === "token" ||
            value === "error" ||
            value === "workflow_handoff" ||
            value === "end"
        );
}

export async function streamChat(
    body: ChatRequest,
    // 回调函数
    // 每解析出一个SSE事件，就调用它
    onEvent: (
        event: StreamEvent
    ) => void,
) {

    const response = await fetch(
        `${API_BASE_URL}/chat/stream`,
        {
            method: "POST",
            headers:{
                "Content-Type":
                    "application/json",
            },
            body: JSON.stringify(body),
        }
    );


    if (!response.ok) {
        throw new Error(
            `Stream error: ${response.status}`
        );
    }


    if (!response.body) {
        throw new Error(
            "Response body is empty"
        );
    }


    // response.body 一个 ReadableStream（可读流）对象，代表 HTTP 响应体中的数据流
    // .getReader() 创建一个流读取器（Reader），用于逐块读取数据
    const reader =
        response.body.getReader();

    // 创建一个文本解码器
    const decoder =
        new TextDecoder();


    let buffer = "";


    while(true){

        const {
            done,
            value,
        } = await reader.read(); // 异步读取流中的下一个数据块


        if(done){
            break;
        }

        // decoder.decode 字节->文字
        buffer += decoder.decode(
            value,
            {
                // true 后续还有数据 为了处理多字节字符（如中文、Emoji）被拆分到两个块中的情况
                stream:true,
            }
        );


        // SSE 一个event结束后 两个换行
        const events =
            buffer.split("\n\n");

        // 拿最后一个元素保存 下一轮继续
        buffer =
            events.pop() ?? "";


        for(
            const event of events
        ){

            if(!event.trim()){
                continue;
            }

            // \n
            // event: token
            // data: {"content":"你好"}
            const lines = event.split("\n");

            // 解析消息类型
            const eventType = lines.find(
                line =>
                line.startsWith("event:")
            )
            ?.replace(
                "event:", 
                ""
            )
            .trim();

            const dataLine =
                lines
                .find(
                    line =>
                    line.startsWith(
                        "data:"
                    )
                );

            // 找不到返回 undefined
            if(!dataLine){
                continue;
            }


            const data =
                dataLine
                .replace(
                    "data:",
                    ""
                )
                .trim();


            let parsed: Record<string, unknown>;

            try{
                
                const parsedValue: unknown =
                    JSON.parse(data);

                if (
                    !parsedValue
                    || typeof parsedValue !== "object"
                    || Array.isArray(parsedValue)
                ) {
                    throw new Error(
                        "SSE data must be a JSON object"
                    );
                }

                parsed = parsedValue as Record<string, unknown>;

                // 解析好的内容 给回调函数
            }catch(error){

                console.error(
                    "SSE parse error",
                    error
                );

                continue;
            }

            if (!isStreamEventType(eventType)) {
                continue;
            }

            // 回调错误属于业务错误，必须传达给调用方。
            onEvent({
                ...parsed,
                type: eventType,
            } as StreamEvent);
        }
    }
}
