from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView


class BaseCRUDAPIView(APIView):

    model = None
    serializer_class = None

    def get(self, request, id=None):
        # If an ID is provided, fetch a single object
        if id:
            obj = get_object_or_404(self.model, id=id)
            serializer = self.serializer_class(obj)
            return Response(serializer.data, status=status.HTTP_200_OK)

        # If no ID is provided, fetch all objects
        objs = self.model.objects.all()
        serializer = self.serializer_class(objs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, id=None):
        if id:
            return Response({"error": "POST method not allowed on specific ID"}, status=status.HTTP_405_METHOD_NOT_ALLOWED)
        # Create a new object
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        # Return validation errors if data is invalid
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request, id=None):
        return self.patch(request, id)

    def patch(self, request, id=None):
        if not id:
            return Response({"error": "Method requires an ID"}, status=status.HTTP_405_METHOD_NOT_ALLOWED)
        # Partial update of an existing object (only provided fields are updated)
        obj = get_object_or_404(self.model, id=id)
        serializer = self.serializer_class(obj, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, id=None):
        if not id:
            return Response({"error": "Method requires an ID"}, status=status.HTTP_405_METHOD_NOT_ALLOWED)
        # Delete an existing object
        obj = get_object_or_404(self.model, id=id)
        obj.delete()
        # Return HTTP 204 No Content for a successful deletion
        return Response(status=status.HTTP_204_NO_CONTENT)
