"use client";

import {
    useEffect,
    useRef,
    useState,
} from "react";


import type {
    Conversation,
    ConversationUpdateRequest,
} from "@/types/chat";


import {
    deleteConversation as deleteConversationRequest,
    getConversations,
    updateConversation,
} from "@/lib/api";

type ConversationMutation = {
    conversationId: string;
    type: "rename" | "delete";
};


export function useConversations(
    refreshKey = 0,
){

    const [
        conversations,
        setConversations
    ] = useState<Conversation[]>([]);


    const [
        loading,
        setLoading
    ] = useState(true);

    const [error,setError]=useState<string|null>(null)

    const [conversationMutation, setConversationMutation] =
        useState<ConversationMutation | null>(null);

    const [renameError, setRenameError] = useState<string | null>(null);

    const [deleteError, setDeleteError] = useState<string | null>(null);

    const mutationInFlightRef = useRef(false);

    const conversationsRequestVersionRef = useRef(0);



    useEffect(()=>{

        let cancelled=false;

        async function load(){

            const requestVersion =
                ++conversationsRequestVersionRef.current;

            try {

                setLoading(true);

                setError(null);

                const data =
                    await getConversations();

                if (
                    cancelled ||
                    requestVersion !== conversationsRequestVersionRef.current
                ) {
                    return;
                }


                setConversations(data);

            } catch(error) {

                if (
                    cancelled ||
                    requestVersion !== conversationsRequestVersionRef.current
                ) {
                    return;
                }

                setError(
                    error instanceof Error ? error.message : "Failed"
                )

            }finally {
                if (!cancelled) {
                    setLoading(false);
                }

            }

        }


        load();

        return ()=> {
            cancelled=true;
        }

    },[refreshKey]);

    async function renameConversation(
        conversationId: string,
        request: ConversationUpdateRequest,
    ): Promise<boolean> {
        if (mutationInFlightRef.current) {
            return false;
        }

        mutationInFlightRef.current = true;
        setConversationMutation({
            conversationId,
            type: "rename",
        });
        setRenameError(null);
        setDeleteError(null);

        try {
            const updatedConversation = await updateConversation(
                conversationId,
                request,
            );

            conversationsRequestVersionRef.current += 1;

            setConversations((current) =>
                current.map((conversation) =>
                    conversation.id === updatedConversation.id
                        ? updatedConversation
                        : conversation,
                ),
            );

            return true;
        } catch (error) {
            setRenameError(
                error instanceof Error
                    ? error.message
                    : "Failed to rename conversation",
            );

            return false;
        } finally {
            mutationInFlightRef.current = false;
            setConversationMutation(null);
        }
    }

    async function deleteConversation(
        conversationId: string,
    ): Promise<boolean> {
        if (mutationInFlightRef.current) {
            return false;
        }

        mutationInFlightRef.current = true;
        setConversationMutation({
            conversationId,
            type: "delete",
        });
        setDeleteError(null);
        setRenameError(null);

        try {
            await deleteConversationRequest(conversationId);

            conversationsRequestVersionRef.current += 1;

            setConversations((current) =>
                current.filter(
                    (conversation) => conversation.id !== conversationId,
                ),
            );

            return true;
        } catch {
            setDeleteError(
                "Failed to delete the conversation. Please try again.",
            );

            return false;
        } finally {
            mutationInFlightRef.current = false;
            setConversationMutation(null);
        }
    }
    function clearRenameError() {
        setRenameError(null);
    }

    function clearDeleteError() {
        setDeleteError(null);
    }

    return {
        conversations,
        loading,
        error,
        conversationMutation,
        renameError,
        deleteError,
        renameConversation,
        deleteConversation,
        clearRenameError,
        clearDeleteError,
    };
}
